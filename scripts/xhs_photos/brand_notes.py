"""给「要正式进菜单」的店补料：一个品牌搜一轮，点开多篇笔记，取正文 + 实拍图。

和 scrape.py 的区别：那个按菜单顺序批量抓全店的封面图；这个是按品牌名深挖 ——
要把几篇笔记的评价合起来写「为什么是这家」，所以正文（desc）比图更重要，图顺带抓。

用法： python brand_notes.py 宽马记大排档 一恒一素 ...
产物： brands/<slug>.json（notes: [{title, desc, likes, url}]，photos: [...]）
      backend/static/date_photos/<slug>/NN.webp
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

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT = HERE / "brands"
IMG = REPO / "backend" / "static" / "date_photos"
OUT.mkdir(exist_ok=True)

NOTES_PER_BRAND = 5
IMGS_TOTAL = 6
IMGS_PER_NOTE = 3
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def slug(s: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fa5]+", "", s)[:24] or "x"


def brand_token(board: str, brand: str) -> str:
    t = re.sub(r"\s+", "", brand.split("·")[0])
    return t[:3]


def get_note(page):
    return page.evaluate("""() => {
        try {
          const s = window.__INITIAL_STATE__ || {};
          const dm = (s.note && (s.note.noteDetailMap || s.note.detailMap)) || {};
          const keys = Object.keys(dm).filter(k => k && k !== 'undefined' && k.length > 10);
          if (!keys.length) return null;
          const id = keys[keys.length - 1];
          const n = dm[id].note;
          return {
            id, title: n.title || '', desc: (n.desc || '').slice(0, 1200),
            likes: (n.interactInfo && n.interactInfo.likedCount) || '',
            author: (n.user && n.user.nickname) || '',
            xsec: n.xsecToken || '',
            tags: (n.tagList || []).map(t => t.name).slice(0, 10),
            images: (n.imageList || []).map(im => ({
              url: im.urlDefault || (im.infoList && im.infoList[0] && im.infoList[0].url) || '',
              w: im.width || 0, h: im.height || 0,
            })).filter(x => x.url),
          };
        } catch (e) { return null; }
    }""")


def download(url: str, dest: Path):
    base = url.split("!")[0]
    cands = [url]
    if "!" in url:
        cands += [base + "!nd_dft_wlteh_webp_3", base + "!nd_dft_webp_3", base]
    for u in cands:
        for ref in ("https://www.xiaohongshu.com/", ""):
            h = {"User-Agent": UA, "Accept": "image/webp,image/*,*/*;q=0.8"}
            if ref:
                h["Referer"] = ref
            try:
                r = requests.get(u, headers=h, timeout=30)
                if r.status_code == 200 and len(r.content) > 15000:
                    dest.write_bytes(r.content)
                    try:
                        with Image.open(dest) as im:
                            im = im.convert("RGB")
                            if im.width > 960:
                                im = im.resize((960, round(im.height * 960 / im.width)), Image.LANCZOS)
                            tmp = dest.with_suffix(".tmp.webp")
                            im.save(tmp, "WEBP", quality=74, method=6)
                            size = im.size
                        tmp.replace(dest)
                        if size[0] < 420:
                            dest.unlink()
                            continue
                        return size
                    except Exception:
                        dest.unlink()
                        continue
            except Exception:
                continue
    return None


def run(page, ctx, brand: str, token: str):
    slug_ = slug(brand)
    fp = OUT / f"{slug_}.json"
    if fp.exists():
        print(f"skip {brand}（已有 {fp.name}）", flush=True)
        return
    print(f"== {brand}", flush=True)
    ok = False
    for attempt in range(3):
        try:
            page.goto("https://www.xiaohongshu.com/search_result/?keyword="
                      + requests.utils.quote(brand + " 杭州"), wait_until="domcontentloaded")
            ok = True
            break
        except Exception as e:
            print(f"   搜索失败({attempt+1}/3): {str(e)[:60]}", flush=True)
            time.sleep(4)
    if not ok:
        return
    time.sleep(5)
    for _ in range(2):
        page.mouse.wheel(0, 2000)
        time.sleep(1.5)

    cards = page.eval_on_selector_all(
        "section.note-item",
        """els => els.map(e => {
            const a = e.querySelector('a[href*="/explore/"]');
            const t = e.querySelector('.footer .title, .title');
            const like = e.querySelector('.like-wrapper .count, .count');
            return {href: a ? a.getAttribute('href') : '', title: t ? t.innerText.trim() : '',
                    likes: like ? like.innerText.trim() : ''};
        }).filter(x => x.href)""")
    # 标题里带品牌的优先
    cards.sort(key=lambda c: 0 if token in re.sub(r"\s", "", c["title"]) else 1)
    print(f"   卡片 {len(cards)}", flush=True)

    notes, photos, seen = [], [], set()
    opened = 0
    tried = 0
    for card in cards:
        if opened >= NOTES_PER_BRAND or len(photos) >= IMGS_TOTAL:
            break
        if tried >= 12:
            break
        try:
            # 直接 goto 带 xsec_token 的笔记 URL —— 搜索结果卡片的 href 里就带着 token，
            # 带上 token 的 URL 能直接打开（不带 token 才回 300031）。点卡片那套在列表虚拟化/
            # 遮挡下很容易超时，或者按下标点串卡，别再用了。
            url = card["href"] if card["href"].startswith("http") else "https://www.xiaohongshu.com" + card["href"]
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(3800)
            tried += 1
            n = get_note(page)
        except Exception as e:
            print(f"   打开笔记失败: {str(e)[:60]}", flush=True)
            n = None
        if not n:
            continue
        # 正文/标题里没品牌词的，直接当串卡丢弃 —— 宁少勿错
        blob = re.sub(r"\s+", "", (n["title"] or "") + (n["desc"] or ""))
        if token not in blob:
            print(f"   ✗ 串了（{n['title'][:18]}）", flush=True)
            continue
        if any(x["id"] == n["id"] for x in notes):
            continue
        n["url"] = (f"https://www.xiaohongshu.com/explore/{n['id']}"
                    + (f"?xsec_token={n['xsec']}&xsec_source=pc_search" if n.get("xsec") else ""))
        notes.append(n)
        opened += 1
        print(f"   · {n['title'][:26]} 👍{n['likes']} {len(n['desc'])}字", flush=True)

        d = IMG / slug_
        d.mkdir(parents=True, exist_ok=True)
        got = 0
        for im in n["images"]:
            if len(photos) >= IMGS_TOTAL or got >= IMGS_PER_NOTE:
                break
            h = hashlib.sha1(im["url"].split("!")[0].encode()).hexdigest()[:10]
            if h in seen:
                continue
            dest = d / f"{len(photos) + 1:02d}.webp"
            size = download(im["url"], dest)
            if not size:
                continue
            seen.add(h)
            got += 1
            photos.append({"file": str(dest), "path": f"/date_photos/{slug_}/{dest.name}",
                           "w": size[0], "h": size[1],
                           "caption": n["title"][:40], "source_url": n["url"],
                           "note_id": n["id"]})

    fp.write_text(json.dumps({"brand": brand, "slug": slug_, "notes": notes, "photos": photos},
                             ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"   完成：{len(notes)} 篇笔记 / {len(photos)} 张图", flush=True)


def main():
    brands = sys.argv[1:]
    if not brands:
        print("用法: python brand_notes.py <品牌名> [品牌名...]")
        return
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(HERE / "profile"), channel="msedge", headless=False,
            viewport={"width": 1240, "height": 940},
            args=["--disable-blink-features=AutomationControlled"])
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        for b in brands:
            run(page, ctx, b, brand_token(b, b))
        ctx.close()


if __name__ == "__main__":
    main()
