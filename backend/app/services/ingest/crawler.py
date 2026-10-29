"""确定性采集器 —— 输入一个源配置，输出统一中间格式。

这里**不调模型**。模型只在 Hermes skill 的下一步负责：
    summary / impact / importance / topics

统一格式（后面所有环节只认这个）：

    {
      "source_key": "qbitai",
      "source_name": "量子位",
      "title": "...",
      "url": "https://...",
      "summary": "RSS 摘要 / 列表页摘要",
      "content": "文章正文纯文本（截断）",
      "published_at": "2026-10-26 18:30:50",
      "topics": ["大模型"],
      "category": "tech",
      "importance": 3,
      "fetch_level": "L0",
      "raw_hash": "sha256:..."
    }
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

from app.config import settings
from app.services.ingest.fetch import (
    canonical_url,
    clean_text,
    extract_content,
    fetch_github,
    fetch_html_with_ladder,
    fetch_json,
    fetch_rss,
    http_get,
    parse_datetime,
    raw_hash,
    strip_html,
)

_FINANCE_WORDS = ("融资", "财报", "股价", "市值", "营收", "IPO", "上市", "估值", "投资", "收购")
_SUMMARY_BOILERPLATE = ("点击查看原文", "阅读原文", "点击阅读全文", "read more", "continue reading")


@dataclass
class CrawlResult:
    source_key: str
    source_name: str
    status: str = "succeeded"          # succeeded / failed / skipped
    fetch_level: str = "L0"
    items: list[dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    detail: dict[str, Any] = field(default_factory=dict)


def _attr(source: Any, key: str, default: Any = None) -> Any:
    if isinstance(source, dict):
        return source.get(key, default)
    return getattr(source, key, default)


def _guess_category(source_category: str, title: str, summary: str) -> str:
    if source_category == "finance":
        return "finance"
    text = f"{title} {summary}"
    if any(w in text for w in _FINANCE_WORDS):
        return "finance"
    return source_category or "tech"


def _guess_importance(title: str) -> int:
    hot = ("发布", "开源", "融资", "IPO", "突破", "首次", "超过", "超越", "重组", "收购")
    return 4 if any(w in title for w in hot) else 3


def _content_lead(content: str, title: str) -> str:
    """从正文开头挑出第一段「像正文的话」，跳过标题、作者、日期、来源。"""
    lines = [line.strip() for line in clean_text(content).split("\n") if line.strip()]
    picked: list[str] = []
    for line in lines:
        if line == title or re.fullmatch(r"[\d\s年月日/:·\-]+", line):
            continue
        if line.startswith("来源") or line in ("量子位", "机器之心", "新智元", "InfoQ", "GitHub"):
            continue
        if len(line) < 12:
            continue
        picked.append(line)
        if sum(len(x) for x in picked) >= 300:
            break
    return " ".join(picked)[:600] if picked else clean_text(content)[:600]


def _best_summary(summary: str, content: str, title: str = "") -> str:
    """RSS 摘要经常只有「点击查看原文」——那就拿正文开头顶上。"""
    s = clean_text(summary)
    low = s.lower()
    # 有些 RSS 摘要以残缺标签开头（例如 `< img src=...`），当作没有摘要
    if len(s) < 40 or s.startswith("<") or any(p in low for p in _SUMMARY_BOILERPLATE):
        return _content_lead(content, title)
    return s


def _normalize_item(
    source: dict,
    *,
    title: str,
    url: str,
    summary: str,
    content: str,
    published: Any,
    topics: list[str],
    fetch_level: str,
    extra: Optional[dict] = None,
) -> Optional[dict]:
    title = clean_text(title)[:255]
    url = (url or "").strip()
    if not title or not url:
        return None

    content = clean_text(content or summary)
    summary = _best_summary(summary, content, title)
    if len(summary) > 600:
        summary = summary[:600].rstrip() + "…"
    if len(content) > 12000:
        content = content[:12000]

    category = _guess_category(source.get("category", "tech"), title, summary)
    return {
        "source_key": source["key"],
        "source_name": source["name"],
        "title": title,
        "url": url,
        "summary": summary,
        "content": content,
        "published_at": published.strftime("%Y-%m-%d %H:%M:%S") if isinstance(published, datetime) else None,
        "topics": [t for t in dict.fromkeys(x for x in topics if x)][:8],
        "category": category,
        "importance": _guess_importance(title),
        "fetch_level": fetch_level,
        "raw_hash": raw_hash(title, content),
        **(extra or {}),
    }


def _within_lookback(published: Optional[datetime], lookback_hours: int) -> bool:
    if published is None:
        return True
    return published >= datetime.now() - timedelta(hours=lookback_hours)


def _dig(data: Any, path: str) -> Any:
    """按 "content.rendered" 这种点路径取值。"""
    cur = data
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _fetch_rss_detail(entry: dict, cfg: dict) -> tuple[str, str, Optional[str]]:
    """RSS 条目正文：优先官方 JSON 详情接口，其次 HTML 阶梯。

    新智元这类站点正文由 JS 渲染，但页面自己消费 WP REST ——
    走同一个接口等价于 L0，且不需要浏览器。
    """
    api = cfg.get("detail_api")
    if api:
        pattern = cfg.get("id_from_url") or r"/(\d+)(?:/)?$"
        ids = re.findall(pattern, entry.get("url") or "")
        if ids:
            detail_url = api.replace("{id}", ids[-1])
            try:
                data = fetch_json(detail_url)
                raw = _dig(data, cfg.get("detail_content_field", "content.rendered"))
                if raw:
                    text = extract_content(raw, cfg.get("content_selectors")) or strip_html(raw)
                    if text:
                        return text, "L0", None
            except Exception as e:  # noqa: BLE001
                return "", "L0", f"{detail_url}: {e}"

    return fetch_html_with_ladder(
        entry["url"],
        content_selectors=cfg.get("content_selectors") or [],
        allow_render=bool(cfg.get("allow_render")),
        wait_for=cfg.get("wait_for"),
    )


def _crawl_rss(source: dict, limit: int, lookback_hours: int) -> CrawlResult:
    cfg = source.get("config") or {}
    max_items = int(source.get("max_items") or limit or settings.ingest_max_items)
    entries = fetch_rss(source["feed_url"], limit=max(max_items * 2, 20))

    items: list[dict] = []
    errors: list[str] = []
    for entry in entries:
        if len(items) >= max_items:
            break
        published = parse_datetime(entry.get("published"))
        if not _within_lookback(published, lookback_hours):
            continue

        summary = entry.get("summary") or ""
        content = summary
        level = "L0"
        if cfg.get("fetch_detail", True):
            try:
                detail, level, detail_error = _fetch_rss_detail(entry, cfg)
                if len(detail) > len(content):
                    content = detail
                if detail_error:
                    errors.append(f"{entry['url']}: {detail_error}")
            except Exception as e:  # noqa: BLE001
                errors.append(f"{entry['url']}: {e}")

        item = _normalize_item(
            source,
            title=entry.get("title", ""),
            url=entry.get("url", ""),
            summary=summary,
            content=content,
            published=published,
            topics=entry.get("tags") or [],
            fetch_level=level,
        )
        if item:
            items.append(item)

    return CrawlResult(
        source_key=source["key"],
        source_name=source["name"],
        items=_dedup(items),
        fetch_level=items[0]["fetch_level"] if items else "L0",
        error=None if items else ("没有新条目" if not errors else "; ".join(errors[:3])),
        detail={"entries": len(entries), "errors": errors[:5]},
    )


def _crawl_json_api(source: dict, limit: int, lookback_hours: int) -> CrawlResult:
    cfg = source.get("config") or {}
    max_items = int(source.get("max_items") or limit or settings.ingest_max_items)
    list_url = source["feed_url"].replace("{limit}", str(max(max_items * 2, 20)))
    data = fetch_json(list_url)
    rows = data.get(cfg.get("list_key", "articles")) if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise RuntimeError("列表 JSON 结构不符合预期")

    items: list[dict] = []
    errors: list[str] = []
    for row in rows:
        if len(items) >= max_items:
            break
        published = parse_datetime(row.get(cfg.get("published_field", "publishedAt")))
        if not _within_lookback(published, lookback_hours):
            continue

        item_id = row.get(cfg.get("id_field", "slug")) or row.get("id")
        title = row.get(cfg.get("title_field", "title"), "")
        summary = strip_html(row.get(cfg.get("summary_field", "content"), "") or "")
        topics = list(row.get(cfg.get("topics_field", "tagList"), []) or [])
        article_url = (cfg.get("article_url") or source["home_url"]).replace("{id}", str(item_id))

        content = summary
        level = "L0"
        if cfg.get("fetch_detail") and item_id:
            detail_url = (cfg.get("detail_url") or "").replace("{id}", str(item_id))
            if detail_url:
                try:
                    detail_data = fetch_json(detail_url)
                    raw_content = (
                        detail_data.get(cfg.get("detail_content_field", "content"))
                        if isinstance(detail_data, dict)
                        else ""
                    )
                    if raw_content:
                        content = extract_content(raw_content, cfg.get("content_selectors")) or strip_html(
                            raw_content
                        )
                        level = "L0"
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{detail_url}: {e}")

        item = _normalize_item(
            source,
            title=title,
            url=article_url,
            summary=summary,
            content=content,
            published=published,
            topics=topics,
            fetch_level=level,
            extra={"external_id": str(item_id) if item_id else None},
        )
        if item:
            items.append(item)

    return CrawlResult(
        source_key=source["key"],
        source_name=source["name"],
        items=_dedup(items),
        fetch_level=items[0]["fetch_level"] if items else "L0",
        error=None if items else ("没有新条目" if not errors else "; ".join(errors[:3])),
        detail={"rows": len(rows), "errors": errors[:5]},
    )


def _crawl_github(source: dict, limit: int, lookback_hours: int) -> CrawlResult:
    cfg = source.get("config") or {}
    max_items = int(source.get("max_items") or limit or settings.ingest_max_items)
    queries = cfg.get("queries") or [cfg.get("query", "topic:llm")]

    # 逐个 topic 查再合并：GitHub 的 `OR` 一旦和 created/stars 限定放一起就返回 0 条
    rows: list[dict] = []
    for query in queries:
        rows.extend(
            fetch_github(
                query,
                per_page=max_items,
                sort=cfg.get("sort", "stars"),
                order=cfg.get("order", "desc"),
                created_within_days=int(cfg.get("created_within_days", 45)),
                min_stars=int(cfg.get("min_stars", 300)),
                token=settings.github_token,
            )
        )
    seen: set[str] = set()
    unique: list[dict] = []
    for row in sorted(rows, key=lambda r: int(r.get("stargazers_count") or 0), reverse=True):
        rid = str(row.get("id") or row.get("full_name") or "")
        if not rid or rid in seen:
            continue
        seen.add(rid)
        unique.append(row)
    rows = unique[:max_items]

    items: list[dict] = []
    for row in rows:
        published = parse_datetime(row.get("updated_at") or row.get("created_at"))
        stars = int(row.get("stargazers_count") or 0)
        topics = list(row.get("topics") or []) + ([row["language"]] if row.get("language") else [])
        summary = row.get("description") or "GitHub 上的新项目"
        summary = f"{summary}（★ {stars:,}）"
        content = (
            f"{row.get('full_name')}\n{summary}\n"
            f"语言：{row.get('language') or '—'} · Stars：{stars}\n"
            f"Topics：{', '.join(row.get('topics') or []) or '—'}"
        )
        item = _normalize_item(
            source,
            title=row.get("full_name") or "",
            url=row.get("html_url") or "",
            summary=summary,
            content=content,
            published=published,
            topics=topics,
            fetch_level="L0",
            extra={"external_id": str(row.get("id") or ""), "stars": stars},
        )
        if item:
            item["importance"] = 4 if stars >= 5000 else 3
            items.append(item)

    return CrawlResult(
        source_key=source["key"],
        source_name=source["name"],
        items=_dedup(items),
        fetch_level="L0",
        error=None if items else "GitHub 搜索没有返回条目",
        detail={"rows": len(rows)},
    )


def _crawl_html(source: dict, limit: int, lookback_hours: int) -> CrawlResult:
    """通用 HTML 源：配置了 link_selector 才能当列表页用。"""
    cfg = source.get("config") or {}
    selector = cfg.get("link_selector")
    if not selector:
        raise RuntimeError("html 源需要配置 config.link_selector（列表页链接选择器）")

    from app.services.ingest.fetch import BeautifulSoup

    if BeautifulSoup is None:
        raise RuntimeError("html 源需要 beautifulsoup4")

    res = http_get(source["feed_url"], level="L1")
    if not res.ok:
        raise RuntimeError(f"列表页拉取失败：{res.status or res.error}")
    soup = BeautifulSoup(res.text, "html.parser")
    max_items = int(source.get("max_items") or limit or settings.ingest_max_items)
    items: list[dict] = []
    for a in soup.select(selector)[:max_items]:
        href = a.get("href") or ""
        if href.startswith("/"):
            href = source["home_url"].rstrip("/") + href
        title = clean_text(a.get_text(" "))
        if not title or not href:
            continue
        try:
            content, level, _ = fetch_html_with_ladder(
                href,
                content_selectors=cfg.get("content_selectors") or [],
                allow_render=bool(cfg.get("allow_render")),
            )
        except Exception:  # noqa: BLE001
            content, level = "", "L1"
        item = _normalize_item(
            source,
            title=title,
            url=href,
            summary="",
            content=content or title,
            published=None,
            topics=[],
            fetch_level=level,
        )
        if item:
            items.append(item)
    return CrawlResult(
        source_key=source["key"],
        source_name=source["name"],
        items=_dedup(items),
        error=None if items else "列表页没有解析出链接",
    )


def _dedup(items: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for item in items:
        key = canonical_url(item.get("url")) or item.get("title", "")
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def crawl_source_sync(source: Any, *, limit: int = 12, lookback_hours: int = 36) -> CrawlResult:
    src = {
        "key": _attr(source, "key"),
        "name": _attr(source, "name"),
        "home_url": _attr(source, "home_url"),
        "feed_url": _attr(source, "feed_url"),
        "kind": _attr(source, "kind", "rss"),
        "level": _attr(source, "level", "L0"),
        "category": _attr(source, "category", "tech"),
        "max_items": _attr(source, "max_items", limit),
        "config": _attr(source, "config", {}) or {},
    }
    try:
        if src["kind"] == "rss":
            return _crawl_rss(src, limit, lookback_hours)
        if src["kind"] == "json_api":
            return _crawl_json_api(src, limit, lookback_hours)
        if src["kind"] == "github":
            return _crawl_github(src, limit, lookback_hours)
        if src["kind"] == "html":
            return _crawl_html(src, limit, lookback_hours)
        raise RuntimeError(f"未知的源类型：{src['kind']}")
    except Exception as e:  # noqa: BLE001
        return CrawlResult(
            source_key=src["key"],
            source_name=src["name"],
            status="failed",
            fetch_level=src["level"],
            error=str(e),
        )


async def crawl_source(source: Any, *, limit: int = 12, lookback_hours: int = 36) -> CrawlResult:
    return await asyncio.to_thread(crawl_source_sync, source, limit=limit, lookback_hours=lookback_hours)
