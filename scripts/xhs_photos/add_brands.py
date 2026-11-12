"""把人工核过的新店写进 date_menu（正式菜单）+ 挂图。

为什么用脚本而不是直接改 SEED：生产库是事实源，SEED 只服务空库首启；
两边要一致，所以这里同一份 ENTRIES 也贴进了 services/date_menu.py 的 SEED。

用法：
    python add_brands.py <base_url> <date_admin_password>
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
S.trust_env = False
H = {"X-Date-Password": PW, "Content-Type": "application/json"}

ENTRIES = [
    dict(
        name="宽马记大排档", branch="上城店（森禾商务广场）", cuisine="潮汕鲜牛肉火锅",
        price=110, score=0, taste_light=4, taste_spicy=1, taste_oil=3,
        taste_label="清淡", taste_kind="light", art="beefpot",
        accent_a="#FDF1E7", accent_b="#F8E2D2", dist_km=4.75, dist_work_km=6.99,
        metro="地铁 4 号线 江锦路站 步行约 0.9 km；上城区四季青街道森禾商务广场",
        reach="4 号线彭埠上车 → 江锦路，约 20 分钟出站；打车约 15 分钟",
        reason="屠场到店一小时的热鲜牛肉，明档现切吊龙 / 匙仁 / 胸口油，清汤涮 8–10 秒配沙茶。大排档桌椅、店里循环周杰伦，热闹但吵 —— 适合不介意声量、只想好好吃肉的晚上。",
        tip="吊龙、匙仁、胸口油必点，蘸料走沙茶 + 炸蒜；烧烤类口碑一般，别点多；12 点后就坐满，11 点前到。",
    ),
    dict(
        name="一恒一素", branch="吉祥餐厅（拱宸桥西 · 小河路 368 号）", cuisine="纯净素 · 蔬食",
        price=90, score=0, taste_light=5, taste_spicy=1, taste_oil=1,
        taste_label="最清淡", taste_kind="light", art="chinese",
        accent_a="#F1F4EC", accent_b="#E3EBDD", dist_km=8.66, dist_work_km=6.33,
        metro="地铁 5 号线 大运河站 步行约 520 米；拱墅区小河路 368 号（小河直街街区）",
        reach="1 号线彭埠 → 打铁关换 5 号线 → 大运河，约 35 分钟；打车约 25 分钟",
        reason="和庆春里同一个路子但更「食堂」：黑松露炒饭、猴头菇做的酸菜鱼、杭味菜烧腐竹，全素却不寡淡。店面安静，吃完能顺着运河走小河直街。",
        tip="黑松露炒饭必点；想吃辣提前说（酸菜鱼能调）；适合想给肠胃减负、又能散步的晚上。",
    ),
    dict(
        name="微风山丘", branch="滨江星光大道", cuisine="餐酒馆 · Brunch · Live",
        price=130, score=0, taste_light=3, taste_spicy=2, taste_oil=3,
        taste_label="可清可重", taste_kind="oil", art="western",
        accent_a="#F3EFE9", accent_b="#E4DCD0", dist_km=9.34, dist_work_km=8.90,
        metro="地铁 6 号线 江汉路站 步行约 0.9 km；滨江星光大道",
        reach="1 号线彭埠 → 火车东站换 6 号线 → 江汉路，约 35 分钟；打车约 25 分钟",
        reason="复古工业风、桌距宽、灯光不晃眼：白天 Brunch，晚上 19:00 驻唱、21:00 乐队，说话不吵。香茅脆皮烤鸡 + 鹿茸菌炖豆腐一重一淡，适合小酌或久坐。",
        tip="烤鸡和油呛牛黄喉是下酒菜，怕辣就配菌菇豆腐中和；想听歌坐 19:00 之后，想安静聊天挑白天。",
    ),
    dict(
        name="Luback Dining", branch="湘湖店（越王路 2077 号 B6）", cuisine="咖啡 · 简餐 · 湖景",
        price=120, score=0, taste_light=3, taste_spicy=1, taste_oil=2,
        taste_label="清淡", taste_kind="light", art="western",
        accent_a="#EFF2EC", accent_b="#DDE4DA", dist_km=17.62, dist_work_km=15.67,
        metro="地铁 1 号线 湘湖站 约 4 km，出站打车 10 分钟；萧山湘湖旅游度假区越王路 2077 号 B6",
        reach="1 号线彭埠 → 湘湖（约 45 分钟）再打车 10 分钟；自驾约 35 分钟，园区有停车",
        reason="白色弧形建筑 + 大草坪 + 落地窗直面湘湖，光影和日落都出片；咖啡、简餐、甜品稳定不踩雷，宠物也友好 —— 按下午茶和拍照排，别当正餐期待。",
        tip="咖啡 + 甜品 + 一份简餐就是标准吃法；晴天傍晚 4–6 点光线最好；出门就是湘湖，可以顺路散步。",
    ),
    dict(
        name="博多天一", branch="湖滨银泰 in77 店", cuisine="日料 · 天妇罗牛排饭",
        price=70, score=0, taste_light=3, taste_spicy=1, taste_oil=4,
        taste_label="偏油", taste_kind="oil", art="sushi",
        accent_a="#F1F4FA", accent_b="#E1E8F4", dist_km=7.14, dist_work_km=2.92,
        metro="地铁 1 号线 龙翔桥站 C 口直连湖滨银泰 in77；延安路 258 号",
        reach="1 号线彭埠直达 7 站，约 18 分钟，出站不用上地面",
        reason="现炸天妇罗 + 铁板牛排饭的组合，一个套餐 42–68 元，饭、汤、泡菜可续；开在 in77 里翻台快，适合「今天不想想吃什么」的一顿。",
        tip="点天妇罗套餐 + 溏心蛋，舒芙蕾当甜品；口味偏甜、味增汤偏淡，重口的人会嫌寡淡。",
    ),
]


def slug(s: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fa5]+", "", s)[:24] or "x"


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def main():
    menu = S.get(f"{BASE}/api/date/admin/items", headers=H, timeout=20).json()
    have = {norm(i["name"]) for i in menu}
    print(f"现有菜单 {len(menu)} 条")

    for e in ENTRIES:
        if norm(e["name"]) in have:
            print(f"  跳过（已有）：{e['name']}")
            continue
        r = S.post(f"{BASE}/api/date/items", headers=H,
                   data=json.dumps(e, ensure_ascii=False).encode("utf-8"), timeout=30)
        if r.status_code != 201:
            print(f"  !! {e['name']} 建档失败 {r.status_code} {r.text[:150]}")
            continue
        item = r.json()
        print(f"  + {e['name']} id={item['id'][:8]} sort={item['sort']}")

        bj = HERE / "brands" / f"{slug(e['name'])}.json"
        if not bj.exists():
            print("     没有图，跳过")
            continue
        rec = json.loads(bj.read_text(encoding="utf-8"))
        photos = [{"path": p["path"], "w": p["w"], "h": p["h"],
                   "caption": p.get("caption", ""), "source_url": p.get("source_url", "")}
                  for p in rec.get("photos", [])]
        if not photos:
            print("     图集为空")
            continue
        rp = S.post(f"{BASE}/api/date/items/{item['id']}/photos", headers=H,
                    data=json.dumps({"photos": photos}, ensure_ascii=False).encode("utf-8"), timeout=30)
        print(f"     图 {rp.status_code} · {len(rp.json()) if rp.ok else rp.text[:100]} 张")

    # 回读核对
    menu = S.get(f"{BASE}/api/date/menu", timeout=20).json()
    print(f"\n回读菜单 {len(menu)} 条：")
    for i in menu[-6:]:
        print(f"  {i['name'][:16]:18} 图{len(i.get('photos') or [])}  ¥{i['price']}  家{i['dist_km']}/司{i['dist_work_km']}")


if __name__ == "__main__":
    main()
