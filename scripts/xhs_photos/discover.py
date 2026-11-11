"""按「现有菜单的特点」去小红书找新餐厅。

思路：
- 现有 18 家的特点是「粤式清淡 + 江浙杭帮 + 有氛围感的西餐/融合 + 人均 90–140 + 商圈地铁店」，
  所以搜索词从这四簇出发（见 QUERIES），不是搜「杭州美食」这种大词。
- 只收卡片级信息（标题/作者/点赞/链接），再点开前几篇拿正文 —— 正文里的「📍店名」才是
  能抽出店名的地方；纯标题很多是「西湖边的宝藏粤菜」这种，抽不出品牌。
- 不做判断：什么叫"像他的口味"由人（或主 agent 读正文）来定，脚本只负责把原料搬回来。

用法： python discover.py [每词最多点开几篇=4]
"""
import json
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
OUT = HERE / "discover"
OUT.mkdir(exist_ok=True)
RAW = OUT / "raw.json"

# 四簇关键词 + 商圈词（现有店全在商场/地铁站上盖）
QUERIES = [
    "杭州 顺德菜 推荐",
    "杭州 打边炉 推荐",
    "杭州 粥底火锅 探店",
    "杭州 猪肚鸡 推荐",
    "杭州 潮汕牛肉火锅 探店",
    "杭州 江浙菜 环境好",
    "杭州 杭帮菜 约会",
    "杭州 蔬食 餐厅 探店",
    "杭州 花园餐厅 独栋",
    "杭州 约会 西餐 出片",
    "杭州 氛围感 餐厅 约会",
    "杭州 日料 约会 推荐",
    "杭州 湖滨银泰 餐厅 推荐",
    "杭州 万象城 餐厅 约会",
    "杭州 嘉里中心 餐厅 推荐",
    "杭州 城西银泰 餐厅 约会",
    "杭州 滨江 餐厅 约会 环境",
]

ENRICH_PER_QUERY = int(sys.argv[1]) if len(sys.argv) > 1 else 4


def load_raw():
    if RAW.exists():
        return json.loads(RAW.read_text(encoding="utf-8"))
    return {"queries": [], "notes": {}}


def save_raw(data):
    RAW.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def norm_id(href: str) -> str:
    m = re.search(r"/explore/([0-9a-f]+)", href or "")
    return m.group(1) if m else ""


def main():
    data = load_raw()
    done = set(data["queries"])
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(HERE / "profile"), channel="msedge", headless=False,
            viewport={"width": 1240, "height": 940},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        for q in QUERIES:
            if q in done:
                print(f"skip {q}（已抓）", flush=True)
                continue
            print(f"== {q}", flush=True)
            page.goto("https://www.xiaohongshu.com/search_result/?keyword=" + q.replace(" ", "%20"),
                      wait_until="domcontentloaded")
            time.sleep(5)
            for _ in range(2):                      # 往下滚两屏，多拿几张卡
                page.mouse.wheel(0, 2400)
                time.sleep(1.6)

            cards = page.eval_on_selector_all(
                "section.note-item",
                """els => els.map(e => {
                    const a = e.querySelector('a[href*="/explore/"]');
                    const t = e.querySelector('.footer .title, .title');
                    const like = e.querySelector('.like-wrapper .count, .count');
                    const auth = e.querySelector('.author .name, .author-wrapper .name');
                    return {
                      href: a ? a.getAttribute('href') : '',
                      title: t ? t.innerText.trim() : '',
                      likes: like ? like.innerText.trim() : '',
                      author: auth ? auth.innerText.trim() : '',
                      cover: (e.querySelector('img') || {}).src || ''
                    };
                }).filter(x => x.href)""")
            new = 0
            for c in cards:
                nid = norm_id(c["href"])
                if not nid or nid in data["notes"]:
                    continue
                c["id"] = nid
                c["query"] = q
                c["url"] = "https://www.xiaohongshu.com" + c["href"] if c["href"].startswith("/") else c["href"]
                data["notes"][nid] = c
                new += 1
            print(f"   卡片 {len(cards)}，新增 {new}（累计 {len(data['notes'])}）", flush=True)

            # 点开前几篇拿正文：搜索结果里点卡片走 SPA 路由，直接 goto 会 300031
            opened = 0
            for card in page.query_selector_all("section.note-item"):
                if opened >= ENRICH_PER_QUERY:
                    break
                try:
                    card.scroll_into_view_if_needed()
                    link = card.query_selector("a[href*='/explore/']")
                    if not link:
                        continue
                    nid = norm_id(link.get_attribute("href"))
                    if not nid or data["notes"].get(nid, {}).get("desc") is not None:
                        continue
                    card.query_selector("a.cover").click()
                    page.wait_for_timeout(3800)
                    info = page.evaluate("""() => {
                        try {
                          const s = window.__INITIAL_STATE__ || {};
                          const dm = (s.note && (s.note.noteDetailMap || s.note.detailMap)) || {};
                          const keys = Object.keys(dm).filter(k => k && k !== 'undefined' && k.length > 10);
                          if (!keys.length) return null;
                          const n = dm[keys[keys.length-1]].note;
                          return {id: keys[keys.length-1], title: n.title || '',
                                  desc: (n.desc || '').slice(0, 600), tags: (n.tagList||[]).map(t=>t.name).slice(0,8)};
                        } catch(e){ return null; }
                    }""")
                    if info and info.get("id") in data["notes"]:
                        data["notes"][info["id"]]["desc"] = info.get("desc", "")
                        data["notes"][info["id"]]["tags"] = info.get("tags", [])
                        if info.get("title"):
                            data["notes"][info["id"]]["full_title"] = info["title"]
                        opened += 1
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(1100)
                except Exception as e:
                    print("   点开出错:", e, flush=True)
                    try:
                        page.keyboard.press("Escape")
                    except Exception:
                        pass
            data["queries"].append(q)
            save_raw(data)
            print(f"   点开 {opened} 篇", flush=True)

        ctx.close()
    print("完成，累计笔记", len(data["notes"]), flush=True)


if __name__ == "__main__":
    main()
