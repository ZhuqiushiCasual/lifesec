"""把 out/*.json 的图集写进 selfsec 的 date_photos 表（走 admin 接口，不直连库）。

用法：
    python import_photos.py [base_url] [password]
默认 http://127.0.0.1:8123 / devpw（本地起的开发实例）。
店按名字对齐（去掉空格比对），对不上就报出来，不猜。
"""
import json
import re
import sys
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8123").rstrip("/")
PW = sys.argv[2] if len(sys.argv) > 2 else "devpw"
S = requests.Session()
S.trust_env = False          # 本机 HTTP_PROXY 是 clash，别让本地请求走代理
H = {"X-Date-Password": PW, "Content-Type": "application/json"}


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def main():
    menu = S.get(f"{BASE}/api/date/menu", timeout=20).json()
    by_name = {norm(i["name"]): i for i in menu}
    print(f"菜单 {len(menu)} 条")

    recs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((HERE / "out").glob("r*.json"))]
    ok = miss = 0
    for rec in recs:
        item = by_name.get(norm(rec["name"]))
        if not item:
            print(f"  !! 菜单里没有：{rec['name']}")
            miss += 1
            continue
        photos = rec["photos"]
        # 笔记标题里没提店名的那几张，来源存疑（搜索页会混进同商圈别的店）：
        # 只要「标题里带店名」的够 3 张，就把存疑的剔掉——宁可少两张，不要上错店的图。
        brand = norm(re.split(r"[·・|｜(（ -]", rec["name"])[0])[:2]
        good = [p for p in photos if brand and brand in norm(p.get("caption", ""))]
        if len(good) >= 3 and len(good) < len(photos):
            print(f"  · {rec['name']}：剔掉 {len(photos) - len(good)} 张标题不含店名的")
            photos = good
        payload = {"photos": [
            {"path": p["path"], "w": p["w"], "h": p["h"],
             "caption": p.get("caption", ""), "source_url": p.get("source_url", "")}
            for p in photos
        ]}
        r = S.post(f"{BASE}/api/date/items/{item['id']}/photos", headers=H,
                   data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), timeout=30)
        if r.status_code != 200:
            print(f"  !! {rec['name']} → {r.status_code} {r.text[:150]}")
            continue
        print(f"  ok {rec['i']:>2} {rec['name']} · {len(payload['photos'])} 张")
        ok += 1

    # 回读核对
    menu = S.get(f"{BASE}/api/date/menu", timeout=20).json()
    got = [(i["name"], len(i.get("photos") or [])) for i in menu]
    print(f"写入 {ok} 家，未匹配 {miss} 家；回读：{sum(n for _, n in got)} 张图")
    for name, n in got:
        if n == 0:
            print("  无图：", name)


if __name__ == "__main__":
    main()
