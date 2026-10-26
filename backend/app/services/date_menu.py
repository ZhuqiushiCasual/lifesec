"""菜单的种子数据与读写小工具。

种子只在表为空时写入一次（`ensure_seed`），之后一切以库为准 —— 后台删光了
也不会在下次启动时"又长回来"。

两个距离口径（都是直线距离）：
    家   = 三花国际（明月桥路×鸿泰路，地铁 1/4 号线 彭埠站 A 口）
    公司 = 黄龙体育中心（黄龙路 1 号，地铁 3/10 号线 黄龙体育中心站）
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.date_menu import DateMenuItem

# 注意：score 是点评快照（0 = 没取到，前台显示成没有分数那一截）。
SEED: list[dict] = [
    dict(
        name="梅溪徐记 · 鲜牛肉火锅", branch="德信中心店", cuisine="潮汕牛肉火锅",
        price=122, score=4.7, taste_light=4, taste_spicy=1, taste_oil=2,
        taste_label="清淡", taste_kind="light", art="beefpot",
        accent_a="#FDF1E7", accent_b="#F8E2D2", dist_km=0.17, dist_work_km=9.08,
        metro="地铁 彭埠站 B 口（1/4 号线）步行 220 米，德信中心 8 幢 2 楼",
        reach="不用坐地铁，下楼就到",
        reason="上城区潮汕牛肉火锅销量榜第 1。清汤涮鲜切牛肉，油烟小、桌距宽，说话不用抬嗓门。",
        tip="牛肉涮 8–10 秒就够；蘸料走沙茶 + 芹菜粒 + 少量酱油，别倒辣酱，否则白汤白涮。",
    ),
    dict(
        name="泥靴 City", branch="平安悦坊店（万象城商圈）", cuisine="西餐 · 牛排",
        price=120, score=4.6, taste_light=2, taste_spicy=1, taste_oil=4,
        taste_label="偏油", taste_kind="oil", art="western",
        accent_a="#F3F1EA", accent_b="#E6E0D2", dist_km=4.73, dist_work_km=8.07,
        metro="地铁 江锦路站（4 号线）B3 口出，平安悦坊 / 万象城商圈，步行约 8 分钟",
        reach="4 号线彭埠上车直达 6 站，约 20 分钟出站",
        reason="上城区牛排打卡人气榜第 2。店里是「郊野」装修，灯光和摆盘都出片，人均 120 在漂亮饭里算克制。",
        tip="两个人点一份牛排 + 一份沙拉 + 一个甜品刚好；牛排五分熟比全熟嫩，双人套餐容易吃不完。",
    ),
    dict(
        name="一痕月", branch="万象城 6 楼 L628", cuisine="时尚中国菜",
        price=230, score=0, taste_light=3, taste_spicy=1, taste_oil=2,
        taste_label="看菜点", taste_kind="light", art="chinese",
        accent_a="#F7F2EC", accent_b="#EADFD2", dist_km=4.76, dist_work_km=8.03,
        metro="地铁 江锦路站（4 号线）B3 口旁直连万象城，上 6 楼",
        reach="和泥靴同一趟车、同一个商场，只差楼层",
        reason="米其林指南入选。复古吊灯 + 欧式橱柜，菜是融合中国菜，酱香马鲛鱼、文火小牛肉口碑稳定。",
        tip="人均 230 起，适合有由头的日子；必须提前订位，茶单过百种，可以直接让服务员配茶。",
    ),
    dict(
        name="禧粤鱼捞 · 斑鱼海鲜粥火锅", branch="亚奥万象天地店", cuisine="粤菜 · 粥底打边炉",
        price=108, score=0, taste_light=5, taste_spicy=1, taste_oil=1,
        taste_label="最清淡", taste_kind="light", art="porridge",
        accent_a="#EFF5F6", accent_b="#DDEBEE", dist_km=4.85, dist_work_km=11.03,
        metro="地铁 6 号线 亚运村站 直连亚奥万象天地，商场 5 层 L535",
        reach="4 号线 1 站到火车东站 → 换 6 号线，约 25–30 分钟",
        reason="粥底涮斑鱼片，鲜而不油，涮完那锅粥才是主角 —— 最清淡的一种火锅。亚奥万象天地是 6 号线亚运村站上盖，出站不用上地面。",
        tip="锅底选粥水 / 清汤，别选麻辣；鱼片下锅 10 秒卷起就捞；蘸料自己配淡一点。",
    ),
    dict(
        name="兰纳小坞 · 泰北家庭料理", branch="西湖湖滨店", cuisine="泰国菜（泰北）",
        price=90, score=4.4, taste_light=2, taste_spicy=3, taste_oil=2,
        taste_label="偏辣", taste_kind="spicy", art="thai",
        accent_a="#F4F7EA", accent_b="#E7F0D8", dist_km=6.95, dist_work_km=3.18,
        metro="地铁 龙翔桥站 B 口（1 号线）出站往北 80 米，学士路 47-3 号",
        reach="1 号线彭埠直达 7 站，约 18 分钟出站",
        reason="杭州东南亚菜热门榜第 3。泰北家庭料理，人均 90 在湖滨算便宜；暖黄灯配绿植，坐得住 —— 但辣度中等偏上。",
        tip="点单时说「微辣」；冬阴功换椰奶版、青咖喱换黄咖喱会柔很多；用菠萝炒饭和芒果糯米饭垫底。",
    ),
    dict(
        name="野三丝 · 贵阳铁板烧", branch="西湖工联 CC 店", cuisine="贵州菜 / 黔菜",
        price=83, score=4.2, taste_light=1, taste_spicy=4, taste_oil=4,
        taste_label="偏辣 · 偏油", taste_kind="spicy", art="grill",
        accent_a="#FDF0EC", accent_b="#F7DCD4", dist_km=7.06, dist_work_km=3.21,
        metro="地铁 龙翔桥站 A 口（1 号线）直连工联 CC，延安路 292 号 4 楼起",
        reach="1 号线彭埠直达 7 站，出站不用上地面",
        reason="上城区贵州菜热门榜第 1。糟辣椒 + 折耳根 + 高温铁板，烟火气足，三四个人点一桌最划算。",
        tip="辣度说「微辣」；折耳根可单独装；铁板油烟大，别穿刚洗的外套。",
    ),
    dict(
        name="寿司郎 Sushiro", branch="黄龙国际中心店", cuisine="日料 · 回转寿司",
        price=119, score=4.4, taste_light=4, taste_spicy=1, taste_oil=2,
        taste_label="清淡", taste_kind="light", art="sushi",
        accent_a="#F1F4FA", accent_b="#E1E8F4", dist_km=9.28, dist_work_km=1.77,
        metro="地铁 文三路站（10 / 19 号线，10 个出口）步行约 5 分钟，学院路 77 号",
        reach="4 号线 1 站到火车东站 → 换 19 号线 3 站到文三路（约 25–30 分钟）",
        reason="西湖区日料打卡人气榜第 1。回转带 + 屏幕点单，节奏自由、一人一份不用互相迁就；离黄龙体育中心只有 1.8 km。",
        tip="工作日上午 11:00 或下午 14:30 最稳；周末先线上取号再去。",
    ),
    dict(
        name="虾佬九 · 打边炉 · 夜宵排档", branch="西湖文化广场店", cuisine="粤式打边炉 / 海鲜排档",
        price=100, score=0, taste_light=3, taste_spicy=3, taste_oil=4,
        taste_label="可清可重", taste_kind="oil", art="porridge",
        accent_a="#F4EFE6", accent_b="#E8DCC8", dist_km=5.96, dist_work_km=3.13,
        metro="地铁 1 号线 西湖文化广场站 C 口 步行 549 米（约 7 分钟），中山北路西湖文化广场 8 号一楼",
        reach="1 号线彭埠上车 4 站直达，约 14 分钟出站",
        reason="海鲜打边炉 + 夜宵排档：淡水澳龙、生蚝、蟹粉捞饭、土鸡起片打边炉都是招牌，人均 100 吃海鲜不多见 —— 代价是排档声量，适合人多图个热闹。",
        tip="想清淡就点土鸡起片打边炉 + 清蒸澳龙，避开蒜蓉 / 香辣 / 油焖；晚上 22 点后才是主场。",
    ),
    dict(
        name="庆春里", branch="嘉里中心北区 NL103", cuisine="江浙菜 · 蔬食",
        price=92, score=4.8, taste_light=4, taste_spicy=1, taste_oil=2,
        taste_label="清淡", taste_kind="light", art="chinese",
        accent_a="#F2F4EF", accent_b="#E2E8DC", dist_km=6.78, dist_work_km=2.85,
        metro="地铁 1/2 号线 凤起路站 C1 口出，步行 220 米；延安路 385 号嘉里中心北区 L1",
        reach="1 号线彭埠直达 7 站，约 20 分钟出站",
        reason="拱墅区江浙菜热门榜第 1（4.8 / ¥92）。庆春系的蔬食馆，黑松露炒饭是招牌，日式静谧的小空间，全程无肉也不寡淡。",
        tip="黑松露炒饭、椒麻豆腐必点；想吃辣提前说，泰式冬阴功可以跳过；工作日午市比晚市好排。",
    ),
]


async def ensure_seed(db: AsyncSession) -> int:
    """表为空时写入种子；返回写入条数（0 = 已有数据，什么都不做）。"""
    count = (await db.execute(select(func.count(DateMenuItem.id)))).scalar_one()
    if count:
        return 0
    for i, row in enumerate(SEED):
        db.add(DateMenuItem(**row, sort=(i + 1) * 10))
    await db.commit()
    return len(SEED)
