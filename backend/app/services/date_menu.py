"""菜单的种子数据与读写小工具。

种子只在表为空时写入一次（`ensure_seed`），之后一切以库为准 —— 后台删光了
也不会在下次启动时"又长回来"。

两个距离口径（都是直线距离）：
    家   = 三花国际（明月桥路×鸿泰路，地铁 1/4 号线 彭埠站 A 口）
    公司 = 黄龙体育中心（黄龙路 1 号，地铁 3/10 号线 黄龙体育中心站）
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.date_menu import DateMenuItem
from app.utils import today_local

# 注入 prompt 的菜单项上限。店名 + 分店 + 菜系一行，80 行约 4KB；
# 正常只有十来家，设上限只是防止后台误操作把 Context 撑爆。
PROMPT_LIMIT = 80

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
        price=105, score=4.8, taste_light=5, taste_spicy=1, taste_oil=1,
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
    dict(
        name="丹粤阁 · 顺德菜", branch="清泰街店", cuisine="粤菜 · 顺德菜",
        price=140, score=4.5, taste_light=4, taste_spicy=2, taste_oil=3,
        taste_label="清淡", taste_kind="light", art="porridge",
        accent_a="#F1F3EE", accent_b="#E3E7DA", dist_km=6.92, dist_work_km=4.48,
        metro="地铁 1 号线 城站站 C 口出，沿清泰街步行约 900 米（10–12 分钟），清泰街 456 号",
        reach="1 号线彭埠直达 4 站到城站，约 15 分钟出站",
        reason="2025 年上榜餐厅（4.5 / ¥140）。顺德做法：桑拿鸡拿大锅上桌蒸、底下那锅鸡汤才是精华，一鱼四吃也稳 —— 清淡，但要多花点时间等位。",
        tip="桑拿鸡、一鱼四吃、吊烤乳鸽必点；想清淡就避开啫啫煲和腊味煲仔饭；排队凶，错峰去或提前取号。",
    ),
    dict(
        name="缦云里 · 花园西餐", branch="湖滨银泰 in77 D 区 3 楼", cuisine="西餐 · 石烧牛排",
        price=109, score=4.4, taste_light=2, taste_spicy=1, taste_oil=3,
        taste_label="偏甜油", taste_kind="oil", art="western",
        accent_a="#FDF0EF", accent_b="#F7DCDA", dist_km=7.25, dist_work_km=3.16,
        metro="地铁 1 号线 龙翔桥站 C 口出，延安路 239 号 湖滨银泰 in77 D 区 3 楼（维多利亚的秘密楼上），步行约 70 米",
        reach="1 号线彭埠直达 7 站到龙翔桥，约 20 分钟出站",
        reason="湖滨商圈西餐销量榜第 1（4.4 / ¥109，到店 8 万+）。整店做成花园：鲜花、绿植、Kitty 摆件，石烧牛排、舒芙蕾、粉色意面出片率最高。",
        tip="两个人一份牛排 + 一份意面 + 一个舒芙蕾刚好；石烧要自己翻面，别穿浅色；周末 17:30 前到，18:00 后等位久。",
    ),
    dict(
        name="兰桂江南", branch="湖滨银泰 in77 E 区 3 楼 301", cuisine="江浙菜",
        price=92, score=4.4, taste_light=4, taste_spicy=1, taste_oil=2,
        taste_label="清淡", taste_kind="light", art="chinese",
        accent_a="#F4F1E9", accent_b="#E8E1D2", dist_km=7.25, dist_work_km=3.16,
        metro="地铁 1 号线 龙翔桥站 B / C 口出，延安路 258 号 湖滨银泰 in77 E 区 3 楼 301 号，步行约 5 分钟",
        reach="1 号线彭埠直达 7 站到龙翔桥，约 20 分钟出站",
        reason="湖滨商圈浙菜打卡人气榜第 7（4.4 / ¥92，到店 6 万+）。泉水牛肉、红烧肉、酒酿馒头是招牌；E 区人流比 C / D 区少，卡座能坐久。",
        tip="泉水牛肉、鲍鱼沃豆腐、清炒时蔬最稳；红烧肉偏甜，两人点一份分着吃；杭椒石锅牛蛙是辣口，避开。",
    ),
    dict(
        name="小筑里 · 独栋花园餐厅", branch="延安路 200 号（西湖店）", cuisine="融合料理 · 西餐",
        price=130, score=0, taste_light=3, taste_spicy=1, taste_oil=3,
        taste_label="看菜点", taste_kind="light", art="western",
        accent_a="#FBF1F3", accent_b="#F3DFE3", dist_km=7.38, dist_work_km=3.5,
        metro="地铁 1 号线 龙翔桥站 C 口出，沿延安路南行，延安路 200 号（花酒间小酒馆旁），步行约 8 分钟",
        reach="1 号线彭埠直达 7 站到龙翔桥，约 20 分钟出站",
        reason="延安路上的独栋花园洋房（携程 4.7 / 17 条；点评分未取到，评分为空）。露台 + 鲜花蜡烛，白天下午茶、晚上正餐都出片，点评上 4.5 万张菜图、1.2 万张环境图。",
        tip="炙烤牛排烩饭、土耳其烤春鸡是招牌；下午茶套餐比正餐划算；别墅位子少，周末要提前订。",
    ),
    dict(
        name="藏鲜工坊", branch="城北万象城店", cuisine="江浙菜 · 海鲜",
        price=120, score=4.6, taste_light=4, taste_spicy=2, taste_oil=2,
        taste_label="清淡", taste_kind="light", art="chinese",
        accent_a="#F1F5F3", accent_b="#DFE9E4", dist_km=12.08, dist_work_km=9.76,
        metro="地铁 4 / 10 号线 杭行路站 E 口直达城北万象城，余杭区 杭行路 1499 号",
        reach="4 号线彭埠直达约 12 站到杭行路，约 30 分钟；12 km，赶时间打车 25–30 分钟",
        reason="北部新城江浙菜热门榜第 2（4.6 / ¥120，到店 1 万+）。台州宁波路子：家烧黄鱼配年糕、沙蒜豆面、清蒸东海三鲜，鲜咸不靠辣。",
        tip="点家烧 / 清蒸 / 汤；川香辣子鸡、湘味小炒肉是辣口别点；黄鱼年糕两人分刚好。",
    ),
    dict(
        name="越稽 · 地道绍兴菜馆", branch="东站德信中心店", cuisine="浙江菜 · 绍兴菜",
        price=125, score=4.6, taste_light=3, taste_spicy=2, taste_oil=3,
        taste_label="鲜咸", taste_kind="light", art="chinese",
        accent_a="#F5F1E8", accent_b="#E9DFCB", dist_km=0.15, dist_work_km=9.11,
        metro="地铁 1 / 4 号线 彭埠站 B 口出，明月桥路 265 号 德信中心 8 幢 2 楼，步行约 220 米",
        reach="下楼就到（离家 0.15 km）",
        reason="火车东站 / 高铁站浙菜好评榜第 2（4.6 / ¥125，到店 1 万+）。糟献鸡、干菜头大河虾、西施豆腐羹、古越鸡汤，鲜咸清口，不油不辣。",
        tip="只点「糟 / 蒸 / 汤」那半边：糟献鸡、西施豆腐羹、古越鸡汤；臭豆腐、霉千张蒸肉饼味道冲，第一次去别点。",
    ),
    dict(
        name="喜禄顺德小馆", branch="东站万象汇店", cuisine="粤菜 · 顺德菜",
        price=110, score=4.6, taste_light=5, taste_spicy=1, taste_oil=2,
        taste_label="最清淡", taste_kind="light", art="porridge",
        accent_a="#EFF3F1", accent_b="#DDE8E3", dist_km=0.32, dist_work_km=8.64,
        metro="地铁 1 号线 火车东站站，和兴路 129 号 东站万象汇（与东站天桥直连）",
        reach="1 号线彭埠上车 1 站到火车东站，全程约 10 分钟",
        reason="上城区顺德菜热门榜第 1（4.6 / ¥110，到店 3 万+）。桑拿鸡大锅上桌蒸、底下那锅鸡汤才是精华，配白灼菜心和双皮奶。",
        tip="桑拿鸡 + 白灼菜心 + 双皮奶；菜单里的麻辣啫牛蛙、啫啫系列重酱又响，想清淡就别碰。",
    ),
    dict(
        name="三折里 · 饮食店", branch="东站万象汇店", cuisine="特色菜 · 轻食米线",
        price=91, score=4.6, taste_light=4, taste_spicy=2, taste_oil=2,
        taste_label="清淡", taste_kind="light", art="chinese",
        accent_a="#F3F4EE", accent_b="#E4E7DA", dist_km=0.32, dist_work_km=8.64,
        metro="地铁 1 号线 火车东站站，和兴路 129 号 东站万象汇（与东站天桥直连）",
        reach="1 号线彭埠上车 1 站到火车东站，全程约 10 分钟",
        reason="上城区特色菜好评榜第 4（4.6 / ¥91，到店 1 万+）。金汤虾滑米线、鲜虾沙拉、薄荷拌牛肉，轻口小份、上菜快。",
        tip="两人一份米线 + 一份拌饭 + 一份沙拉就够；想吃热汤点金汤虾滑；这里是轻食小馆，别指望正餐阵仗。",
    ),
    dict(
        name="叶马茶楼", branch="六和塔店（之江路 92 号）", cuisine="江浙菜 · 海鲜",
        price=134, score=4.7, taste_light=4, taste_spicy=1, taste_oil=2,
        taste_label="清淡", taste_kind="light", art="chinese",
        accent_a="#F4F2EC", accent_b="#E7E1D4", dist_km=13.95, dist_work_km=7.76,
        metro="之江路 92 号（六和塔停车场旁、六和塔公园北侧）；地铁 4 号线 水澄桥站 B 口出，换 4 路 / 318 路 / 39 路到「六和塔」站",
        reach="4 号线彭埠上车直达水澄桥（不换乘），出站换公交 2 站；13.9 km，直接打车约 30 分钟",
        reason="点评 4.7 / ¥134，杭州糖醋排骨菜品榜第 2 名，到店 5 万+ —— 比嘉里中心店的 4.4 高一个档。叶马的老店（2015 年从三台山搬来），钱塘江边一排落地窗，清蒸大白条、石锅海胆豆腐、黄鱼年糕是招牌；米其林指南入选，2018 黑珍珠。",
        tip="清淡就点清蒸 / 家烧：清蒸大白条、石锅海胆豆腐、黄鱼年糕，两人 2 菜 1 汤够；周一至周五只做 11:00–13:30、17:00–20:30 两段，周末午市到 14:00；靠窗位先到先得。",
    ),
    dict(
        name="捞王猪肚鸡火锅", branch="嘉里中心店 3 幢 4 层 L403", cuisine="粤式猪肚鸡火锅",
        price=120, score=4.3, taste_light=4, taste_spicy=1, taste_oil=2,
        taste_label="清淡", taste_kind="light", art="beefpot",
        accent_a="#F5F0E6", accent_b="#E9DDC9", dist_km=6.81, dist_work_km=2.85,
        metro="地铁 1 / 2 号线 凤起路站 C1 口出，延安路 353 号 嘉里中心 3 幢 4 层 L403",
        reach="1 号线彭埠直达 6 站到凤起路，约 18 分钟出站",
        reason="嘉里中心 4 层的猪肚鸡老店（4.3 / ¥120，到店 3 万+）。白胡椒猪肚鸡清汤锅，涮鲜切牛肉和时蔬都是原味，汤底能直接喝两碗。",
        tip="锅底只点胡椒猪肚鸡，别加麻辣鸳鸯；先喝汤再涮；两人点半份牛肉 + 手工虾滑 + 时蔬。",
    ),
    # 品牌在杭州只有两家：西溪印象城（3 号线洪园站旁）与良渚玉鸟集。
    # 良渚离东站 22 km，西溪印象城 14 km —— 后者是这两家里唯一值得放上来的。
    dict(
        name="竹间·三喜 · 无国界料理", branch="西溪印象城 A 座 2 楼", cuisine="创意菜 · 无国界料理（泰式）",
        price=90, score=4.5, taste_light=3, taste_spicy=2, taste_oil=2,
        taste_label="泰式微辣", taste_kind="spicy", art="thai",
        accent_a="#F5F2E9", accent_b="#E7DFCC", dist_km=14.33, dist_work_km=6.48,
        metro="地铁 3 号线 洪园站 B 口出，步行约 100 米（商场负一层与地铁口直连）；余杭区 五常大道 1 号 西溪印象城 A 座 2 楼",
        reach="1 号线彭埠上车 4 站到西湖文化广场，换 3 号线 10 站到洪园站，全程约 45 分钟；14.3 km",
        reason="西溪印象城创意菜销量榜第 1（4.5 / ¥90，到店 8000+）。泰式 + 无国界的漂亮饭小馆，室内外都有座位，绿植和木质调出片；人均 90 在同类里算克制。",
        tip="斑斓叶包鸡、泰式菠萝饭、冬阴功海鲜锅是招牌；泰式偏酸辣，怕辣点单时直接说「不辣」；两个人 4–5 个菜就够；饭点排队凶，先线上取号。",
    ),
    # 老秦两家店（滨江伟业路 / 萧山明星路），滨江总店更近、也是必吃榜那家。
    dict(
        name="老秦凉都黄牛肉馆", branch="滨江总店（伟业路）", cuisine="贵州 · 黄牛肉火锅",
        price=100, score=4.7, taste_light=4, taste_spicy=1, taste_oil=2,
        taste_label="清汤涮牛肉", taste_kind="light", art="beefpot",
        accent_a="#F6F0E4", accent_b="#E9DDC7", dist_km=13.54, dist_work_km=9.26,
        metro="地铁 6 号线 伟业路站 A 口出，步行约 340 米；滨江区 伟业路 298-101 号（江南大道 × 伟业路）",
        reach="4 号线彭埠上车直达中医药大学，换 6 号线 1 站到伟业路，全程约 35 分钟；13.5 km",
        reason="2026 大众点评入围餐厅 + 高德 2025 杭州必吃榜（4.7 / ¥100，到店 1 万+），网红徐沐言也去吃过这家。贵州六盘水吃法：清汤锅涮现切极品生牛肉，加一份牛杂拼盘，两个人一百出头就吃饱。",
        tip="必点极品生牛肉（¥69）、牛杂、牛胸口油，配玉米饼；清汤锅别加辣，蘸水自己调（多加花生碎）；10:30 开门就排，22 点后反而好进；营业到凌晨 3 点。",
    ),
    dict(
        name="T-yoogee", branch="杭州首店 · 万象城 2 期 L1 层 S180", cuisine="创意菜 · 融合料理 + 甜品",
        price=128, score=4.3, taste_light=3, taste_spicy=2, taste_oil=3,
        taste_label="微辣偏甜", taste_kind="spicy", art="western",
        accent_a="#FBF1F0", accent_b="#F3DEDC", dist_km=4.75, dist_work_km=8.05,
        metro="地铁 4 号线 江锦路站 B3 口出直连万象城；2 期 L1 层 S180（上城区 富春路 701 号）",
        reach="4 号线彭埠上车直达 6 站，约 20 分钟出站；和泥靴、一痕月同一个商场，只是期数不同",
        reason="万象城创意菜（4.3 / ¥128），深圳开过来的杭州首店。空间和摆盘都出片；鲜辣炖牛筋拌粉、炭烧雪花牛排拼盘、龙井冰沙配茶油烤菠萝是热门，网友说甜品水准够单开一家甜品店（巧克力提拉米苏）。",
        tip="稳的组合：牛舌牛肝菌拌饭 + 炭烧雪花牛排拼盘 + 一份甜品；拌粉偏辣，怕辣换拌饭；首店排队，避开 12:00 / 18:30；甜品值得单独来一次。",
    ),
    # ── 2026-11 从候选清单里人工复核后转正的 5 家 ──────────────
    # 来源：小红书多篇探店笔记（见 scripts/xhs_photos/brands/），人均是估算，score 没取到点评分
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


async def ensure_seed(db: AsyncSession) -> int:
    """表为空时写入种子；返回写入条数（0 = 已有数据，什么都不做）。"""
    count = (await db.execute(select(func.count(DateMenuItem.id)))).scalar_one()
    if count:
        return 0
    for i, row in enumerate(SEED):
        db.add(DateMenuItem(**row, sort=(i + 1) * 10))
    await db.commit()
    return len(SEED)


async def prompt_items(db: AsyncSession, limit: int = PROMPT_LIMIT) -> list[DateMenuItem]:
    """给对话 Context 用的菜单项。

    包含 hidden 项：hidden 只控制 /date 前台是否展示，不改变「这家店存在」的事实；
    用户提到它时仍然应该能关联上。用 sort 排序，保证同样的输入得到同样的 prompt。
    """
    stmt = select(DateMenuItem).order_by(DateMenuItem.sort, DateMenuItem.id).limit(limit)
    return list((await db.execute(stmt)).scalars().all())


def render_prompt(items: list[DateMenuItem], today: date | None = None) -> str:
    """拼成模型能直接读的「今天 + 可关联餐厅清单」。

    今天日期是给 visited_on 解析相对日期用的（"昨天/上周六"），
    所以即使没有菜单项也保留第一行。
    """
    day = today or today_local()
    lines = [f"【今天】{day:%Y-%m-%d}"]
    if not items:
        lines.append("【约会餐厅清单】（暂无；店名对不上时 restaurant_id 填 null）")
        return "\n".join(lines)

    lines.append("【约会餐厅清单】（提到的店如果能对上，就用这里的 id 关联；id 不要改写）")
    for item in items:
        bits = [item.name]
        if item.branch:
            bits.append(f"（{item.branch}）")
        if item.cuisine:
            bits.append(f"｜{item.cuisine}")
        lines.append(f"- id={item.id}  {''.join(bits)}")
    return "\n".join(lines)
