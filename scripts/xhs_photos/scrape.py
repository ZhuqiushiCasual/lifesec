"""从小红书抓每家餐厅的实拍图。

思路（为什么这么做）：
- 搜索页登录后能读，笔记**直接 goto URL** 会被 300031 挡（"当前笔记暂时无法浏览"），
  但在搜索结果里**点开卡片**走的是 SPA 内部路由，弹层正常加载 —— 所以用 click 不用 goto。
- 图集从弹层里的 `__INITIAL_STATE__.note.noteDetailMap[noteId].note.imageList` 拿，
  比扫 DOM 稳（DOM 只挂当前视口附近的几张）。
- 每家取前 3 篇「标题里带品牌名」的笔记，每篇取前 3 张，合并去重后最多 6 张。
- 图片下到 backend/static/date_photos/<slug>/，清单写 out/<slug>.json（断点续抓）。

用法：
    python scrape.py                # 全部
    python scrape.py 3 7 12         # 只抓第 3、7、12 家（1-based）
"""
import hashlib
import json
import re
import sys
import time
from pathlib import Path

import requests
from PIL import Image
from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[2]      # selfsec/
HERE = Path(__file__).resolve().parent
MENU = json.loads((HERE / "menu.json").read_text(encoding="utf-8"))   # 菜单快照：{'i','name','branch'}
OUT = HERE / "out"
OUT.mkdir(exist_ok=True)
IMGROOT = REPO / "backend" / "static" / "date_photos"
IMG_TARGET = 6          # 每家最多留几张
NOTES_PER_ITEM = 3      # 看几篇笔记
IMGS_PER_NOTE = 3       # 每篇取几张
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def log(msg):
    print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)


def brand_of(name: str) -> str:
    """「梅溪徐记 · 鲜牛肉火锅」→ 梅溪徐记；「泥靴 City」→ 泥靴。"""
    head = re.split(r"[·・|｜(（ -]", name)[0].strip()
    return head or name


# 搜索词个别要加地标/分店，否则搜出来全是同商圈别的店
KEYWORD = {
    8: "虾佬九 西湖文化广场",
    22: "T-yoogee 杭州西餐",
}


def slug_of(row: dict) -> str:
    return f"r{row['i']:02d}"


def grab_note_state(page):
    """读当前弹层那篇笔记：标题 / 正文 / 图（宽高 + URL）。"""
    return page.evaluate("""() => {
        try {
          const s = window.__INITIAL_STATE__ || {};
          const dm = (s.note && (s.note.noteDetailMap || s.note.detailMap)) || {};
          const keys = Object.keys(dm).filter(k => k && k !== 'undefined' && k.length > 10);
          if (!keys.length) return {err: 'no-note'};
          const id = keys[keys.length - 1];
          const n = dm[id] && dm[id].note;
          if (!n) return {err: 'no-detail'};
          return {
            id,
            title: n.title || '',
            desc: (n.desc || '').slice(0, 300),
            tagList: (n.tagList || []).map(t => t.name).filter(Boolean).slice(0, 6),
            images: (n.imageList || []).map(im => ({
              w: im.width || 0, h: im.height || 0,
              url: im.urlDefault || (im.infoList && im.infoList[0] && im.infoList[0].url) || ''
            })).filter(x => x.url),
          };
        } catch (e) { return {err: String(e)}; }
    }""")


def download(url: str, dest: Path) -> tuple[int, int] | None:
    """下原图（尽量换成大图后缀），返回 (w, h)；失败返回 None。"""
    candidates = [url]
    base = url.split("!")[0]
    if "!" in url:
        candidates += [base + "!nd_dft_wlteh_webp_3", base + "!nd_dft_webp_3", base]
    for u in candidates:
        for ref in ("https://www.xiaohongshu.com/", ""):
            headers = {"User-Agent": UA, "Accept": "image/avif,image/webp,image/*,*/*;q=0.8"}
            if ref:
                headers["Referer"] = ref
            try:
                r = requests.get(u, headers=headers, timeout=30)
                if r.status_code == 200 and len(r.content) > 15000:
                    dest.write_bytes(r.content)
                    try:
                        with Image.open(dest) as im:
                            w, h = im.size
                        if w < 420:          # 太小的缩略图不要
                            dest.unlink()
                            continue
                        if dest.suffix.lower() != ".webp" and im.format:
                            pass
                        return w, h
                    except Exception:
                        dest.unlink()
                        continue
            except Exception:
                continue
    return None


def scrape_item(page, row, seen_hashes):
    brand = brand_of(row["name"])
    slug = slug_of(row)
    outdir = IMGROOT / slug
    outdir.mkdir(parents=True, exist_ok=True)

    page.goto("https://www.xiaohongshu.com/search_result/?keyword="
              + requests.utils.quote(KEYWORD.get(row["i"], brand + " 杭州")),
              wait_until="domcontentloaded")
    time.sleep(5.5)

    cards = page.eval_on_selector_all(
        "section.note-item",
        """els => els.map(e => {
            const a = e.querySelector('a[href*="/explore/"]');
            const t = e.querySelector('.footer .title, .title');
            return {href: a ? a.getAttribute('href') : '', title: t ? t.innerText.trim() : ''};
        }).filter(x => x.href)""")
    log(f"  [{slug}] {brand}: 搜索结果 {len(cards)} 条")

    # 标题里带品牌名的优先，其次按原顺序
    ordered = [c for c in cards if brand.replace(" ", "")[:3] in c["title"].replace(" ", "")] + \
              [c for c in cards if c not in [x for x in cards if brand.replace(" ", "")[:3] in x["title"].replace(" ", "")]]

    photos, notes_used = [], []
    for card in ordered:
        if len(photos) >= IMG_TARGET or len(notes_used) >= NOTES_PER_ITEM:
            break
        try:
            idx = page.eval_on_selector_all(
                "section.note-item a[href*='/explore/']",
                "els => els.map(e => e.getAttribute('href'))").index(card["href"])
            page.query_selector_all("section.note-item")[idx].query_selector("a.cover").click()
            page.wait_for_timeout(4200)
            data = grab_note_state(page)
        except Exception as e:
            log(f"    open failed: {e}")
            data = {"err": str(e)}

        if not data or data.get("err") or not data.get("images"):
            log(f"    skip note: {data.get('err') if data else 'none'} / {card['title'][:20]}")
            page.keyboard.press("Escape")
            page.wait_for_timeout(1200)
            continue

        note_id = data["id"]
        note_url = f"https://www.xiaohongshu.com/explore/{note_id}"
        caption = (data.get("title") or card["title"] or "").strip()[:40]
        log(f"    note 「{caption[:24]}」 {len(data['images'])} 张")
        notes_used.append(note_id)

        got_here = 0
        for im in data["images"]:
            if len(photos) >= IMG_TARGET or got_here >= IMGS_PER_NOTE:
                break
            url = im["url"]
            h = hashlib.sha1(url.split("!")[0].encode()).hexdigest()[:10]
            if h in seen_hashes:
                continue
            dest = outdir / f"{len(photos) + 1:02d}.webp"
            size = download(url, dest)
            if not size:
                continue
            seen_hashes.add(h)
            got_here += 1
            photos.append({
                "file": str(dest),
                "path": f"/date_photos/{slug}/{dest.name}",
                "w": size[0], "h": size[1],
                "caption": caption,
                "source_url": note_url,
            })
            log(f"      + {dest.name} {size[0]}x{size[1]} {dest.stat().st_size // 1024}KB")

        page.keyboard.press("Escape")
        page.wait_for_timeout(1400)

    rec = {"i": row["i"], "name": row["name"], "branch": row.get("branch", ""), "slug": slug, "photos": photos}
    (OUT / f"{slug}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"  [{slug}] 完成 {len(photos)} 张")
    return rec


def main():
    only = {int(x) for x in sys.argv[1:]} if len(sys.argv) > 1 else None
    rows = [r for r in MENU if (only is None or r["i"] in only)]
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(HERE / "profile"), channel="msedge", headless=False,
            viewport={"width": 1240, "height": 940},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        seen = set()
        for row in rows:
            existing = OUT / f"{slug_of(row)}.json"
            if existing.exists():
                log(f"skip {row['i']} (已抓过)")
                continue
            try:
                scrape_item(page, row, seen)
            except Exception as e:
                log(f"  !! {row['name']} 失败: {e}")
        ctx.close()


if __name__ == "__main__":
    main()
