"""按品牌名逐个核一遍：搜到店 → 点开第一篇 → 拿标题/正文/首图。

为什么要按品牌再搜一次：discover.py 收的是「标题里出现过的店名」，但标题里没有地址、人均；
品牌搜索的结果页第一篇通常是探店正文，正文里带「📍 地址 / 人均」，这才是能复核的信息。

用法： python probe_candidates.py
输出： cand/<slug>.json + cand/<slug>.jpg（首图，稍后压到 400px）
"""
import json
import re
import time
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
CAND = HERE / "cand"
CAND.mkdir(exist_ok=True)

BRANDS = [
    # 粤式清淡（顺德 / 打边炉 / 粥底 / 潮汕牛肉 / 猪肚鸡）
    "汕尾尾鲜切鸡火锅", "莫氏鸡煲", "中贸阿嬷清远鸡打边炉", "宽马记大排档",
    "泉市鲜活牛肉店", "阿盼鱼捞", "朱富贵火锅", "乔村二十八道",
    # 江浙 / 杭帮 / 蔬食
    "如院 餐厅", "山河风味", "南山南餐厅", "朴竺", "一恒一素", "KIN Restaurant", "汉舍小馆", "荣小馆",
    # 有氛围的西餐 / 融合
    "香楼", "Luback Dining", "PoDo", "O'eat", "BELLOCO倍乐", "微风山丘", "Moment·盈",
    # 日料
    "博多天一", "笑颜日料",
]

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def slug(s: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fa5]+", "", s)[:24] or "x"


def get_note(page):
    return page.evaluate("""() => {
        try {
          const s = window.__INITIAL_STATE__ || {};
          const dm = (s.note && (s.note.noteDetailMap || s.note.detailMap)) || {};
          const keys = Object.keys(dm).filter(k => k && k !== 'undefined' && k.length > 10);
          if (!keys.length) return null;
          const id = keys[keys.length-1];
          const n = dm[id].note;
          return {
            id, title: n.title || '', desc: (n.desc || '').slice(0, 800),
            likes: (n.interactInfo && n.interactInfo.likedCount) || '',
            author: (n.user && n.user.nickname) || '',
            xsec: n.xsecToken || '',
            images: (n.imageList || []).map(im => im.urlDefault || (im.infoList && im.infoList[0] && im.infoList[0].url)).filter(Boolean),
          };
        } catch(e){ return null; }
    }""")


def download(url, dest):
    for ref in ("https://www.xiaohongshu.com/", ""):
        h = {"User-Agent": UA}
        if ref:
            h["Referer"] = ref
        try:
            r = requests.get(url, headers=h, timeout=30)
            if r.status_code == 200 and len(r.content) > 12000:
                dest.write_bytes(r.content)
                return True
        except Exception:
            continue
    return False


def main():
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(HERE / "profile"), channel="msedge", headless=False,
            viewport={"width": 1240, "height": 940},
            args=["--disable-blink-features=AutomationControlled"])
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        for brand in BRANDS:
            fp = CAND / f"{slug(brand)}.json"
            if fp.exists():
                print(f"skip {brand}", flush=True)
                continue
            print(f"== {brand}", flush=True)
            ok = False
            for attempt in range(3):
                try:
                    page.goto("https://www.xiaohongshu.com/search_result/?keyword="
                              + requests.utils.quote(brand + " 杭州"), wait_until="domcontentloaded")
                    ok = True
                    break
                except Exception as e:
                    print(f"   打开搜索失败({attempt+1}/3): {str(e)[:80]}", flush=True)
                    time.sleep(4)
            if not ok:
                fp.write_text(json.dumps({"brand": brand, "error": "goto-failed"}, ensure_ascii=False), encoding="utf-8")
                continue
            time.sleep(4.5)
            cards = page.query_selector_all("section.note-item")
            if not cards:
                print("   没结果", flush=True)
                fp.write_text(json.dumps({"brand": brand, "error": "no-result"}, ensure_ascii=False), encoding="utf-8")
                continue
            # 优先点标题里带品牌词的卡片
            target, pos = None, 0
            for i, c in enumerate(cards[:8]):
                t = c.inner_text()[:60]
                if brand.split()[0][:3] in re.sub(r"\s", "", t):
                    target, pos = c, i
                    break
            if target is None:
                target = cards[0]
            try:
                target.scroll_into_view_if_needed()
                target.query_selector("a.cover").click()
                page.wait_for_timeout(4200)
                note = get_note(page)
            except Exception as e:
                note = None
                print("   点开失败:", e, flush=True)
            page.keyboard.press("Escape")
            page.wait_for_timeout(800)

            if not note:
                fp.write_text(json.dumps({"brand": brand, "error": "no-note"}, ensure_ascii=False), encoding="utf-8")
                print("   拿不到正文", flush=True)
                continue

            rec = {"brand": brand, "note_id": note["id"], "title": note["title"], "desc": note["desc"],
                   "likes": note["likes"], "author": note["author"],
                   "url": f"https://www.xiaohongshu.com/explore/{note['id']}" +
                          (f"?xsec_token={note['xsec']}&xsec_source=pc_search" if note.get("xsec") else ""),
                   "cover": f"cand/{slug(brand)}.jpg" if note.get("images") else ""}
            if note.get("images"):
                ok = download(note["images"][0], CAND / f"{slug(brand)}.jpg")
                if not ok:
                    rec["cover"] = ""
            fp.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"   标题: {note['title'][:34]} | {len(note['desc'])} 字 | 👍{note['likes']}", flush=True)

        ctx.close()


if __name__ == "__main__":
    main()
