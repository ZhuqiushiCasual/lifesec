"""从「候选页留下的那一篇笔记」直接取图（搜索结果被限流时的备用路径）。

cand/<brand>.json 里存着带 xsec_token 的笔记 URL，带 token 的笔记页能直接开；
开出来取 imageList，下 6 张压到 960 / WebP 74。

用法： python photos_from_note.py 宽马记大排档 一恒一素 微风山丘 博多天一
"""
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
IMG = REPO / "backend" / "static" / "date_photos"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def slug(s: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fa5]+", "", s)[:24] or "x"


def download(url: str, dest: Path):
    base = url.split("!")[0]
    for u in [url] + ([base + "!nd_dft_wlteh_webp_3", base] if "!" in url else []):
        for ref in ("https://www.xiaohongshu.com/", ""):
            h = {"User-Agent": UA}
            if ref:
                h["Referer"] = ref
            try:
                r = requests.get(u, headers=h, timeout=30)
                if r.status_code == 200 and len(r.content) > 15000:
                    dest.write_bytes(r.content)
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
                        return None
                    return size
            except Exception:
                continue
    return None


def main():
    brands = sys.argv[1:]
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(HERE / "profile"), channel="msedge", headless=False,
            viewport={"width": 1180, "height": 900},
            args=["--disable-blink-features=AutomationControlled"])
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        for b in brands:
            rec = json.loads((HERE / "cand" / f"{slug(b)}.json").read_text(encoding="utf-8"))
            url = rec.get("url") or f"https://www.xiaohongshu.com/explore/{rec.get('note_id')}"
            print(f"== {b}  {url[:80]}", flush=True)
            try:
                page.goto(url, wait_until="domcontentloaded")
                time.sleep(5)
            except Exception as e:
                print("   打开失败", str(e)[:60], flush=True)
                continue
            info = page.evaluate("""() => { const s=window.__INITIAL_STATE__||{}; const dm=(s.note&&(s.note.noteDetailMap||s.note.detailMap))||{};
              const k=Object.keys(dm).filter(x=>x&&x!=='undefined'&&x.length>10);
              if(!k.length) return null;
              const n=dm[k[k.length-1]].note;
              return {title:n.title||'', images:(n.imageList||[]).map(im=>im.urlDefault||(im.infoList&&im.infoList[0]&&im.infoList[0].url)).filter(Boolean)}; }""")
            if not info:
                print("   笔记页打不开（限流）", flush=True)
                continue
            d = IMG / slug(b)
            d.mkdir(parents=True, exist_ok=True)
            got = 0
            photos = []
            for u in info["images"][:6]:
                dest = d / f"{got + 1:02d}.webp"
                size = download(u, dest)
                if not size:
                    continue
                got += 1
                photos.append({"path": f"/date_photos/{slug(b)}/{dest.name}", "w": size[0], "h": size[1],
                               "caption": info["title"][:40], "source_url": rec.get("url", "")})
                print(f"   + {dest.name} {size[0]}x{size[1]}", flush=True)
            out = HERE / "brands" / f"{slug(b)}.json"
            prev = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
            prev.setdefault("brand", b)
            prev.setdefault("notes", [])
            prev["photos"] = photos
            out.write_text(json.dumps(prev, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"   {b}: {got} 张", flush=True)
        ctx.close()


if __name__ == "__main__":
    main()
