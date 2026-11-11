"""把探到的笔记整理成 /date/candidates 用的数据 + 压缩封面。

CURATED 里是我（主 agent）逐条读过正文后做的取舍：留下符合「清淡 / 粤式 / 江浙 / 有氛围」
且人均大致在 150 以内的，超预算或明显踩雷的写进 DROPPED 并说明原因 —— 取舍要留痕，
下次再抓不会把同一批又捞回来。

用法： python build_candidates.py
产物： backend/static/date_candidates.json
      backend/static/date_photos/cand/<slug>.webp（400px 宽）
"""
import json
import re
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
CAND = HERE / "cand"
DST = REPO / "backend" / "static" / "date_photos" / "cand"
DST.mkdir(parents=True, exist_ok=True)

# (分组, 店名, 区域, 菜系, 人均(可空), 复核提示, 抓自哪个品牌的笔记文件)
CURATED = [
    # ── 粤式清淡：鸡汤煲 / 粥底 / 潮汕鲜牛（现有菜单里最厚的一簇）
    ("yue", "汕尾尾鲜切鸡火锅", "商业体内（未标注）", "粤式 · 清远鸡打边炉", None,
     "径山鲜鸡现烫 15 秒，汤清回甘、不用冻货；但笔记里说门口贴了转让、老板想换地址，去前先确认还在原地。",
     "汕尾尾鲜切鸡火锅"),
    ("yue", "中贸阿嬷清远鸡打边炉", "未标注", "粤式 · 清远鸡打边炉", None,
     "清鸡汤锅，桌距宽、还有小包间；博主给的评价是「及格但不算惊艳」，胜在清淡好聊、冬天一锅汤。",
     "中贸阿嬷清远鸡打边炉"),
    ("yue", "宽马记大排档", "上城区", "潮汕鲜牛肉火锅", None,
     "明档现切吊龙 / 匙仁，复古大排档风格；人均比连锁潮牛低，代价是声量偏大，适合不怕热闹的场合。",
     "宽马记大排档"),
    ("yue", "泉市鲜活牛肉店", "未标注", "潮汕鲜牛肉", None,
     "二刷的鲜牛肉店：吊龙 10 秒、五花腱 15 秒，肉燥饭每次都点；只有口味，没有环境。",
     "泉市鲜活牛肉店"),
    ("yue", "阿盼鱼捞 · 斑鱼粥火锅", "未标注", "粤式 · 粥底打边炉", 100,
     "和禧粤鱼捞同一个路子（斑鱼 + 粥底），人均 100 上下；博主说菜不惊艳，但粥底值得二刷。",
     "阿盼鱼捞"),
    ("yue", "朱富贵火锅", "滨江 · 星光大道", "小火锅", None,
     "只有一条笔记、信息很少，先当「路过可看」：滨江商圈的网红小火锅。",
     "朱富贵火锅"),

    # ── 江浙 / 杭帮 / 台州 / 素食
    ("jiang", "南山南餐厅", "西湖 · 青芝坞", "杭帮菜", None,
     "黄鱼烧年糕、南山香烤鸡、元宝虾，典型杭帮甜咸口；青芝坞在西湖景区里，吃完能顺着走一圈。",
     "南山南餐厅"),
    ("jiang", "一恒一素", "拱墅 · 小河直街", "纯净素", None,
     "黑松露炒饭 + 猴头菇版酸菜鱼，安静不吵，和庆春里同一路子；运河边，吃完能逛小河直街。",
     "一恒一素"),
    ("jiang", "汉舍小馆", "未标注（原黑珍珠）", "京菜 · 烤鸭", 120,
     "人均 120+ 的烤鸭馆，厨师当面片鸭有仪式感；掉了黑珍珠但烤鸭仍在线，不吃鸭就别去。",
     "汉舍小馆"),
    ("jiang", "荣小馆", "万象城", "台州菜", None,
     "新荣记平替：家烧黄鱼、沙蒜豆面、手打年糕；要提前一周订位，人均比新荣记低一档。",
     "荣小馆"),
    ("jiang", "乔村二十八道", "萧山 · 钱塘江边", "中餐（粤浙融合）", None,
     "四层全窗、每桌有隔断，钱塘江一线视野；胡椒猪肚煲被夸爆，但人均可能超 150，先复核价格。",
     "乔村二十八道"),

    # ── 有氛围的西餐 / 融合（出片、能聊天）
    ("west", "PoDo in PoDo", "西溪印象城", "创意西餐 · 融合", None,
     "五刷的店，摆盘和氛围都出片；碳烤猪颈肉 + 辣奶油海鲜意面，约会向。",
     "PoDo"),
    ("west", "微风山丘", "滨江", "餐酒馆", None,
     "复古工业风 + 驻唱，晚上灯暗但不吵；烤鸡重、菌菇豆腐淡，一桌能坐很久。",
     "微风山丘"),
    ("west", "BELLOCO 倍乐", "嘉里中心 HL106B", "韩式创意料理", 150,
     "人均 150 顶格的韩餐，铁锅猪颈肉和奶油意面是招牌；5 点线上取号可以完全不排队。",
     "BELLOCO倍乐"),
    ("west", "Luback Dining", "湘湖", "西餐", None,
     "草坪 + 露台，出片极强；食物评价一般（披萨偏甜）。当「看景吃饭」用，别冲菜去。",
     "Luback Dining"),
    ("west", "山河风味", "恒隆顶楼（运河边）", "南北融合菜", None,
     "宋韵木质调独栋 + 双厨坐镇的新店，菜品口碑好；人均待查，适合有由头的日子。",
     "山河风味"),

    # ── 日料
    ("jp", "博多天一", "湖滨银泰 in77", "日料 · 天妇罗", None,
     "现炸天妇罗套餐 + 舒芙蕾，翻台快；偏甜、味增汤寡淡，胜在人均低、位置就在湖滨。",
     "博多天一"),
]

GROUPS = {
    "yue": ("粤式清淡（鸡汤煲 / 粥底 / 潮汕鲜牛）",
            "现有菜单里最厚的一簇：5 家都是清汤、少辣、能一边涮一边说话。这组按「清汤锅 + 鲜切」继续找。"),
    "jiang": ("江浙 · 杭帮 · 台州 · 素食",
              "菜单里 5 家江浙系（庆春里 / 兰桂江南 / 越稽 / 叶马 / 藏鲜工坊），共同点是本地口味、清淡、能久坐。"),
    "west": ("有氛围的西餐 / 融合（出片、能聊天）",
             "泥靴 / 缦云里 / T-yoogee 那一类：灯光摆盘值钱，菜不难吃，适合要一点仪式感的晚上。"),
    "jp": ("日料", "寿司郎是唯一一家日料，补一个同类：人均低、翻台快、随时能去。"),
}

DROPPED = [
    ("莫氏鸡煲", "笔记原文「一般，没啥特别的」，6/10，不值得占一个名额"),
    ("如院", "高端中餐，人均远超 150 的档位"),
    ("香楼", "西湖景区里，两个人吃了 1000+，超预算"),
    ("笑颜日料", "余杭区夫妻店，人均 500+"),
    ("朴竺 · 植物料理", "米其林绿星，超预算（与庆春里 / 一恒一素重复）"),
    ("O'eat", "测评里培根踩雷、鸡翅一般"),
    ("KIN Restaurant", "品牌对不上：抓到的正文写的是金泰兰，不是这家"),
    ("Moment·盈", "是演出场地，不是餐厅"),
]


def slug(s: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fa5]+", "", s)[:24] or "x"


def main():
    groups = {}
    for key, name, *_ in CURATED:
        groups.setdefault(key, [])

    total_bytes = 0
    for key, name, area, cuisine, price, reason, src in CURATED:
        rec = json.loads((CAND / f"{slug(src)}.json").read_text(encoding="utf-8"))
        s = slug(name)
        cover_path = ""
        jpg = CAND / f"{slug(src)}.jpg"
        if jpg.exists():
            with Image.open(jpg) as im:
                im = im.convert("RGB")
                if im.width > 400:
                    im = im.resize((400, round(im.height * 400 / im.width)), Image.LANCZOS)
                out = DST / f"{s}.webp"
                im.save(out, "WEBP", quality=78, method=6)
                total_bytes += out.stat().st_size
            cover_path = f"/date_photos/cand/{s}.webp"
        groups[key].append({
            "name": name, "area": area, "cuisine": cuisine, "price": price,
            "reason": reason, "note_title": rec.get("title", ""),
            "note_url": rec.get("url", ""), "likes": rec.get("likes", ""),
            "cover": cover_path,
        })

    data = {
        "generated": "2026-11-12",
        "note": "这批是从小红书按你的口味搜回来的备选，还没进菜单。每家都挂了原始笔记链接，点开能看原文再决定；"
                "觉得可以喊我一声，我按标准字段（人均 / 两个距离 / 地铁 / 点菜小抄）补进菜单。",
        "stats": {"queries": 17, "notes": 399, "candidates": len(CURATED)},
        "keywords": [
            {"k": "口味", "v": "清 4 分以上（9/18 家）、辣度 1（10/18）→ 清汤、少辣、少油"},
            {"k": "菜系", "v": "粤式清淡（顺德 / 打边炉 / 粥底 / 猪肚鸡 / 潮汕牛）· 江浙杭帮 · 有氛围的西餐 · 日料"},
            {"k": "预算", "v": "现有 83–142，中位 114；目标带 90–140，硬上限 150"},
            {"k": "场景", "v": "两人、能坐下说话、桌距宽 / 有隔断 / 卡座、灯光好、出片"},
            {"k": "位置", "v": "商场或地铁上盖（湖滨 in77 / 嘉里 / 万象城 / 德信 / 西溪印象城 / 滨江），离她家彭埠或她公司黄龙近"},
            {"k": "评分", "v": "整条菜单 4.2–4.8，多数 ≥4.4；低于 4.3 基本不进"},
        ],
        "groups": [
            {"key": k, "title": v[0], "why": v[1], "count": len(groups[k]), "items": groups[k]}
            for k, v in GROUPS.items() if groups[k]
        ],
        "dropped": [{"name": n, "why": w} for n, w in DROPPED],
        "foot": "抓取时间 2026-11-12，小红书搜索结果（17 组关键词、399 篇笔记）。笔记里没写人均的，价格那一栏就空着，"
                "不代表便宜。排除项："
                + "；".join(f"{n}（{w}）" for n, w in DROPPED) + "。",
    }
    out = REPO / "backend" / "static" / "date_candidates.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"写入 {out}：{len(CURATED)} 家，封面 {total_bytes/1024:.0f} KB")
    for g in data["groups"]:
        print(f'  {g["title"]}: {g["count"]}')


if __name__ == "__main__":
    main()
