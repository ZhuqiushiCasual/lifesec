"""换掉某家店的图集：换个帖子的图重来一遍。

场景：`/date` 上某家的封面不满意（或者图太旧），要换成别的笔记里的照片。
要求换成全新的一组，所以：
  1. 搜品牌 → 跳过已经用过的笔记 id（记录在 brands/<slug>.json 里）
  2. 打开 2–3 篇新笔记，每篇取 2 张，凑够 6 张
  3. 下到 backend/static/date_photos/<slug>-vN/，再用 POST /items/{id}/photos 整组替换
  4. 新用到的笔记追加进 brands/<slug>.json（描述依据可追溯）

用法：
    python swap_photos.py "Luback Dining" <base_url> <date_admin_password>
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
IMG = REPO / "backend" / "static" / "date_photos"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

NOTES = 3          # 换几篇笔记
IMGS_PER_NOTE = 2
TOTAL = 6


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
                        continue
                    return size
            except Exception:
                continue
    return None


def note_of(page):
    return page.evaluate("""() => {
        try {
          const s = window.__INITIAL_STATE__ || {};
          const dm = (s.note && (s.note.noteDetailMap || s.note.detailMap)) || {};
          const k = Object.keys(dm).filter(x => x && x !== 'undefined' && x.length > 10);
          if (!k.length) return null;
          const id = k[k.length - 1], n = dm[id].note;
          return {id, title: n.title || '', desc: (n.desc || '').slice(0, 800),
                  likes: (n.interactInfo && n.interactInfo.likedCount) || '',
                  xsec: n.xsecToken || '',
                  images: (n.imageList || []).map(im => im.urlDefault || (im.infoList && im.infoList[0] && im.infoList[0].url)).filter(Boolean)};
        } catch (e) { return null; }
    }""")


def main():
    brand = sys.argv[1] if len(sys.argv) > 1 else "Luback Dining"
    base = (sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8123").rstrip("/")
    pw = sys.argv[3] if len(sys.argv) > 3 else "devpw"
    S = requests.Session(); S.trust_env = False
    H = {"X-Date-Password": pw, "Content-Type": "application/json"}

    fp = HERE / "brands" / f"{slug(brand)}.json"
    rec = json.loads(fp.read_text(encoding="utf-8"))
    used_ids = {n["id"] for n in rec.get("notes", [])}
    token = re.sub(r"\s+", "", brand.split("·")[0])[:3]

    # 目录换个后缀，别覆盖正在用的图（前台还在读旧路径）
    n = 1
    while (IMG / f"{slug(brand)}-v{n}").exists():
        n += 1
    outdir = IMG / f"{slug(brand)}-v{n}"
    outdir.mkdir(parents=True, exist_ok=True)
    print(f"目标目录 {outdir}")

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(HERE / "profile"), channel="msedge", headless=False,
            viewport={"width": 1240, "height": 940},
            args=["--disable-blink-features=AutomationControlled"])
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://www.xiaohongshu.com/search_result/?keyword="
                  + requests.utils.quote(brand + " 杭州"), wait_until="domcontentloaded")
        time.sleep(5)
        for _ in range(2):
            page.mouse.wheel(0, 2200); time.sleep(1.5)
        cards = page.evaluate("""() => {
            const f = window.__INITIAL_STATE__ && window.__INITIAL_STATE__.search && window.__INITIAL_STATE__.search.feeds;
            const arr = f && (f._value || f.value || f);
            if (!Array.isArray(arr)) return [];
            return arr.map(x => ({id: x.id, xsec: x.xsecToken || '',
                                  title: (x.noteCard && x.noteCard.displayTitle) || ''}));
        }""")
        print(f"卡片 {len(cards)}")
        BAD = ("难吃", "踩雷", "格局太低", "不会再", "避雷", "失望")

        new_notes, photos = [], []
        tried = 0
        for c in cards:
            if len(new_notes) >= NOTES or len(photos) >= TOTAL:
                break
            if tried >= 12:
                break
            if not c["id"] or c["id"] in used_ids:
                continue
            if any(b in c["title"] for b in BAD):
                print(f"  ✗ 跳过负面帖（{c['title'][:18]}）"); continue
            tried += 1
            url = (f"https://www.xiaohongshu.com/explore/{c['id']}"
                   + (f"?xsec_token={c['xsec']}&xsec_source=pc_search" if c["xsec"] else ""))
            try:
                page.goto(url, wait_until="domcontentloaded")
                time.sleep(4)
                note = note_of(page)
            except Exception as e:
                print("  打开失败", str(e)[:50]); note = None
            if not note:
                print("  笔记打不开（限流？）"); continue
            blob = re.sub(r"\s+", "", note["title"] + note["desc"])
            if token not in blob:
                print(f"  ✗ 不是这家（{note['title'][:16]}）"); continue
            if note["id"] in used_ids or any(x["id"] == note["id"] for x in new_notes):
                continue
            note["url"] = (f"https://www.xiaohongshu.com/explore/{note['id']}"
                           + (f"?xsec_token={note['xsec']}&xsec_source=pc_search" if note.get("xsec") else ""))
            new_notes.append(note)
            print(f"  · {note['title'][:26]} 👍{note['likes']} {len(note['images'])} 张")
            got = 0
            for u in note["images"]:
                if len(photos) >= TOTAL or got >= IMGS_PER_NOTE:
                    break
                dest = outdir / f"{len(photos) + 1:02d}.webp"
                size = download(u, dest)
                if not size:
                    continue
                got += 1
                photos.append({"path": f"/date_photos/{outdir.name}/{dest.name}",
                               "w": size[0], "h": size[1],
                               "caption": note["title"][:40], "source_url": note["url"]})
                print(f"    + {dest.name} {size[0]}x{size[1]}")
        ctx.close()

    if not photos:
        print("没拿到新图，放弃（没动线上）")
        return

    # 先只落盘（base 传 "-"），图片 scp 上去之后再单独写库 —— 否则前台会短暂 404
    if base == "-":
        rec.setdefault("notes", []).extend(
            {"id": n["id"], "title": n["title"], "desc": n["desc"], "likes": n["likes"], "url": n["url"]}
            for n in new_notes)
        rec["photos"] = photos
        rec["photos_dir"] = outdir.name
        fp.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"已落盘 {len(photos)} 张到 {outdir.name}，未写库（base='-'）；图片传完再跑写库")
        return

    # 写库：整组替换
    menu = S.get(f"{base}/api/date/admin/items", headers=H, timeout=20).json()
    item = next((i for i in menu if re.sub(r"\s+", "", i["name"]) == re.sub(r"\s+", "", brand)), None)
    if not item:
        print("菜单里找不到这家"); return
    payload = {"photos": [{"path": p["path"], "w": p["w"], "h": p["h"],
                           "caption": p["caption"], "source_url": p["source_url"]} for p in photos]}
    r = S.post(f"{base}/api/date/items/{item['id']}/photos", headers=H,
               data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), timeout=30)
    print(f"写库 {r.status_code} · {len(r.json()) if r.ok else r.text[:120]} 张")

    # 记录新用到的笔记（描述依据可追溯）
    rec.setdefault("notes", []).extend(
        {"id": n["id"], "title": n["title"], "desc": n["desc"], "likes": n["likes"], "url": n["url"]}
        for n in new_notes)
    rec["photos"] = photos
    rec["photos_dir"] = outdir.name
    fp.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")

    back = S.get(f"{base}/api/date/menu", timeout=20).json()
    one = next(i for i in back if i["id"] == item["id"])
    print(f"回读 {one['name']}：{len(one.get('photos') or [])} 张 · 封面 {one['photos'][0]['path'] if one.get('photos') else '-'}")


if __name__ == "__main__":
    main()
