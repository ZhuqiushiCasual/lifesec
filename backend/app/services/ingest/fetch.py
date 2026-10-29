"""采集层的最底层：HTTP / RSS / JSON / HTML 正文。

刻意把「拿数据」和「判断值不值得推」分开：
这一层只负责把页面变成纯文本，不调模型、不做重要性判断。

降级链（与 `docs/采集-技术选型对比.md` 对齐）：

    L0    RSS / sitemap / 官方 JSON / 官方 API
    L1    普通 HTTP 客户端
    L1.5  curl_cffi（TLS 指纹伪装；装了才启用）
    L2    Playwright（真浏览器；装了且源配置 allow_render 才启用）
    L3    Camoufox（本实现不内置，留给个别硬骨头源单独接）

所有可选依赖都用「有就用、没有就退」的写法，保证离线测试和精简部署也能跑。
"""

from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

from app.config import settings

try:  # 生产/测试环境通常已经有（openai / fastapi 会带）
    import httpx
except Exception:  # noqa: BLE001
    httpx = None  # type: ignore[assignment]

try:
    import feedparser
except Exception:  # noqa: BLE001
    feedparser = None  # type: ignore[assignment]

try:
    from bs4 import BeautifulSoup
except Exception:  # noqa: BLE001
    BeautifulSoup = None  # type: ignore[assignment]

try:
    from curl_cffi import requests as curl_requests
except Exception:  # noqa: BLE001
    curl_requests = None  # type: ignore[assignment]

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

_TRACKING_PREFIXES = ("utm_", "spm", "from", "source", "ref", "share_", "scene", "click_id")


@dataclass
class FetchResult:
    url: str
    status: int
    text: str = ""
    content_type: str = ""
    level: str = "L0"
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None and 200 <= self.status < 400 and bool(self.text)


def _headers(extra: Optional[dict] = None) -> dict:
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
        "Accept-Encoding": "identity",
    }
    if extra:
        headers.update(extra)
    return headers


def _urllib_get(url: str, headers: dict, timeout: float) -> FetchResult:
    try:
        req = Request(url, headers=headers)
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            content_type = resp.headers.get("Content-Type", "")
            charset = resp.headers.get_content_charset() or "utf-8"
            try:
                text = raw.decode(charset, errors="replace")
            except LookupError:
                text = raw.decode("utf-8", errors="replace")
            return FetchResult(url=url, status=resp.status, text=text, content_type=content_type)
    except Exception as e:  # noqa: BLE001
        return FetchResult(url=url, status=0, error=str(e))


def http_get(
    url: str,
    *,
    timeout: float = 25.0,
    headers: Optional[dict] = None,
    level: str = "L0",
    impersonate: bool = False,
) -> FetchResult:
    """一次 HTTP GET。httpx 优先，失败退 urllib；403/405 可再走 curl_cffi。"""
    h = _headers(headers)

    if httpx is not None:
        try:
            with httpx.Client(follow_redirects=True, timeout=timeout) as client:
                resp = client.get(url, headers=h)
                result = FetchResult(
                    url=str(resp.url),
                    status=resp.status_code,
                    text=resp.text,
                    content_type=resp.headers.get("content-type", ""),
                    level=level,
                )
                if resp.status_code in (401, 403, 405, 429) and curl_requests is not None:
                    return _curl_get(url, h, timeout, level, result)
                return result
        except Exception as e:  # noqa: BLE001
            last_error = str(e)
    else:
        last_error = "httpx 未安装"

    if curl_requests is not None:
        return _curl_get(url, h, timeout, level, None)

    fallback = _urllib_get(url, h, timeout)
    fallback.level = level
    if fallback.error is None and last_error and fallback.status == 0:
        fallback.error = last_error
    return fallback


def _curl_get(
    url: str,
    headers: dict,
    timeout: float,
    level: str,
    previous: Optional[FetchResult],
) -> FetchResult:
    """L1.5：把 TLS / HTTP2 指纹伪装成 Chrome。"""
    try:
        resp = curl_requests.get(
            url,
            headers=headers,
            timeout=timeout,
            impersonate="chrome",
            allow_redirects=True,
        )
        return FetchResult(
            url=url,
            status=resp.status_code,
            text=resp.text,
            content_type=resp.headers.get("content-type", ""),
            level="L1.5",
        )
    except Exception as e:  # noqa: BLE001
        if previous is not None:
            previous.error = previous.error or str(e)
            return previous
        return FetchResult(url=url, status=0, level="L1.5", error=str(e))


def render_with_playwright(url: str, wait_for: Optional[str] = None, timeout_ms: int = 30000) -> FetchResult:
    """L2：真浏览器渲染。只有装了 Playwright 且源配置显式允许时才调用。"""
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception as e:  # noqa: BLE001
        return FetchResult(url=url, status=0, level="L2", error=f"Playwright 未安装：{e}")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=UA)
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            if wait_for:
                page.wait_for_selector(wait_for, timeout=15000)
            html_text = page.content()
            browser.close()
        return FetchResult(url=url, status=200, text=html_text, content_type="text/html", level="L2")
    except Exception as e:  # noqa: BLE001
        return FetchResult(url=url, status=0, level="L2", error=str(e))


def fetch_html_with_ladder(
    url: str,
    *,
    content_selectors: Optional[list[str]] = None,
    allow_render: bool = False,
    wait_for: Optional[str] = None,
) -> tuple[str, str, Optional[str]]:
    """返回 (正文, 实际级别, 错误)。失败时正文为空，错误说明原因。"""
    result = http_get(url, level="L1")
    text = extract_content(result.text, content_selectors) if result.ok else ""
    if len(text) >= 300:
        return text, result.level, None

    # L1 拿到空壳 / 403 / 405 → L1.5
    if result.status in (401, 403, 405, 429) or len(text) < 300:
        alt = _curl_get(url, _headers(), 25.0, "L1.5", result)
        alt_text = extract_content(alt.text, content_selectors) if alt.ok else ""
        if len(alt_text) > len(text):
            text, result = alt_text, alt
        if len(text) >= 300:
            return text, result.level, None

    # L2 只对显式开了 allow_render 的源启用
    if allow_render:
        rendered = render_with_playwright(url, wait_for=wait_for)
        if rendered.ok:
            rendered_text = extract_content(rendered.text, content_selectors)
            if len(rendered_text) > len(text):
                return rendered_text, "L2", None
        return text, "L2", rendered.error

    return text, result.level, result.error


# ── RSS / Atom ────────────────────────────────────────────
def fetch_rss(url: str, limit: int = 20) -> list[dict[str, Any]]:
    res = http_get(url, level="L0")
    if not res.ok:
        raise RuntimeError(f"RSS 拉取失败：{res.status or res.error}")

    entries: list[dict[str, Any]] = []
    if feedparser is not None:
        parsed = feedparser.parse(res.text)
        for e in parsed.entries[:limit]:
            content = ""
            if getattr(e, "content", None):
                content = " ".join(c.get("value", "") for c in e.content)
            entries.append(
                {
                    "title": (e.get("title") or "").strip(),
                    "url": (e.get("link") or "").strip(),
                    "summary": strip_html(e.get("summary") or content),
                    "published": e.get("published") or e.get("updated"),
                    "tags": [t.get("term", "") for t in e.get("tags", []) if t.get("term")],
                    "raw": e,
                }
            )
        return entries

    # feedparser 没装：用 ElementTree 兜底（RSS 2.0 / Atom）
    try:
        root = ET.fromstring(res.text)
    except ET.ParseError as e:
        raise RuntimeError(f"RSS 解析失败：{e}") from e

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    items = root.findall(".//item")
    if not items:
        items = root.findall(".//atom:entry", ns)
    for item in items[:limit]:
        def _text(tag: str) -> str:
            node = item.find(tag)
            if node is None:
                node = item.find(f"atom:{tag}", ns)
            return (node.text or "").strip() if node is not None else ""

        link = _text("link")
        if not link:
            node = item.find("atom:link", ns)
            if node is not None:
                link = node.attrib.get("href", "")
        categories = [c.text.strip() for c in item.findall("category") if c.text]
        entries.append(
            {
                "title": _text("title"),
                "url": link,
                "summary": strip_html(_text("description") or _text("summary") or _text("content")),
                "published": _text("pubDate") or _text("published") or _text("updated"),
                "tags": categories,
                "raw": None,
            }
        )
    return entries


# ── JSON ──────────────────────────────────────────────────
def fetch_json(url: str, headers: Optional[dict] = None) -> Any:
    res = http_get(url, level="L0", headers=headers)
    if not res.ok:
        snippet = (res.text or "").strip()[:200]
        raise RuntimeError(f"JSON 拉取失败：{res.status or res.error}{' · ' + snippet if snippet else ''}")
    try:
        return json.loads(res.text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"JSON 解析失败：{e}") from e


# ── GitHub ────────────────────────────────────────────────
def fetch_github(
    query: str,
    *,
    per_page: int = 10,
    sort: str = "stars",
    order: str = "desc",
    created_within_days: int = 45,
    min_stars: int = 300,
    token: str = "",
) -> list[dict[str, Any]]:
    since = (datetime.now() - timedelta(days=created_within_days)).strftime("%Y-%m-%d")
    # GitHub 的 OR 必须整体加括号，否则 `topic:a OR topic:b created:>...`
    # 会被解析成非法查询（API 直接 422）
    base = query.strip()
    if " OR " in base and not (base.startswith("(") and base.endswith(")")):
        base = f"({base})"
    q = f"{base} created:>{since} stars:>={min_stars}"
    params = urlencode({"q": q, "sort": sort, "order": order, "per_page": per_page})
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = fetch_json(f"https://api.github.com/search/repositories?{params}", headers=headers)
    return list(data.get("items") or [])


# ── 正文抽取 ──────────────────────────────────────────────
def strip_html(text: str) -> str:
    if not text:
        return ""
    if BeautifulSoup is not None:
        soup = BeautifulSoup(text, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()
        return clean_text(soup.get_text("\n"))
    text = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return clean_text(html_lib.unescape(text))


def extract_content(html_text: str, selectors: Optional[list[str]] = None) -> str:
    """从 HTML 里抽正文：先试源配置给的选择器，再用「段落最多的容器」兜底。"""
    if not html_text:
        return ""

    if BeautifulSoup is None:
        return strip_html(html_text)

    soup = BeautifulSoup(html_text, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()

    best = ""
    for selector in selectors or []:
        node = soup.select_one(selector)
        if node is None:
            continue
        text = clean_text(node.get_text("\n"))
        if len(text) > len(best):
            best = text
    if len(best) >= 500:
        return _scrub_tags(best)[:20000]

    # 兜底：给每个父容器按「子段落文字总长」打分
    scores: dict[int, tuple[int, Any]] = {}
    for p in soup.find_all(["p", "li", "blockquote", "h2", "h3"]):
        t = clean_text(p.get_text(" "))
        if len(t) < 30:
            continue
        parent = p.parent
        if parent is None:
            continue
        key = id(parent)
        total, _ = scores.get(key, (0, parent))
        scores[key] = (total + len(t), parent)
    if scores:
        _, node = max(scores.values(), key=lambda x: x[0])
        text = clean_text(node.get_text("\n"))
        if len(text) > len(best):
            best = text

    if len(best) < 200:
        best = clean_text(soup.get_text("\n"))
    return _scrub_tags(best)[:20000]


def _scrub_tags(text: str) -> str:
    """清掉残缺标签（例如量子位 RSS 正文里的 `< img src=...`）。

    BeautifulSoup 把 `</ img` 这种畸形写法当纯文本，直接 get_text 会留在正文里。
    """
    if not text or "<" not in text:
        return text
    return clean_text(re.sub(r"<\s*/?\s*[A-Za-z][^>]{0,400}>", " ", text))


def clean_text(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = [line.strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line).strip()


# ── 时间 / URL / 哈希 ─────────────────────────────────────
def parse_datetime(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip()
        dt = None
        for fmt in (
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y/%m/%d %H:%M:%S",
            "%Y/%m/%d %H:%M",
            "%Y-%m-%d",
            "%Y/%m/%d",
        ):
            try:
                dt = datetime.strptime(s, fmt)
                break
            except ValueError:
                continue
        if dt is None:
            try:
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            except ValueError:
                pass
        if dt is None:
            try:
                dt = parsedate_to_datetime(s)
            except (TypeError, ValueError):
                return None

    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone(timedelta(hours=settings.tz_offset_hours))).replace(tzinfo=None)
    return dt


def canonical_url(url: Optional[str]) -> str:
    """去追踪参数后的 URL，用于幂等 / 跨源去重。"""
    if not url:
        return ""
    parsed = urlparse(url.strip())
    query = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if not any(k.lower().startswith(p) or k.lower() == p for p in _TRACKING_PREFIXES)
    ]
    path = parsed.path.rstrip("/") or "/"
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            "",
            urlencode(sorted(query)),
            "",
        )
    )


def raw_hash(title: str, content: str) -> str:
    return "sha256:" + hashlib.sha256(f"{title}\n{content}".encode("utf-8", errors="ignore")).hexdigest()[:24]


def now_stamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")
