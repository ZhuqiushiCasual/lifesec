"""算每家店到「最近地铁站」的距离，并给 >500 m 的那些查停车场。

数据来源与口径：
- 店铺坐标：百度 POI（和 coords.py 同一套 BD09MC → WGS84 换算）
- 地铁站：杭州 1/2/3/4/5/6/10/19 号线的主要站点（百度 POI，一次拉好缓存进 stations.json）
- 停车场：百度 POI 搜「<店名> 停车场」「<商圈/路名> 停车场」，只留 800 m 内的
- 全是**直线距离**，跟菜单上「离家 / 离公司」一个口径

用法：
    python metro_parking.py            # 全菜单体检
    python metro_parking.py 宽马记大排档  # 只看某一家
"""
import json
import sys
from pathlib import Path

sys.argv = [sys.argv[0]] + sys.argv[1:]
import coords  # 复用坐标换算 / haversine / poi_wgs84

HERE = Path(__file__).resolve().parent
CACHE = HERE / "stations.json"

STATIONS = [
    # 1 号线
    "湘湖站", "滨康路站", "西兴站", "滨和路站", "江陵路站", "近江站", "婺江路站", "城站", "定安路站",
    "龙翔桥站", "凤起路站", "武林广场站", "西湖文化广场站", "打铁关站", "闸弄口站", "火车东站站",
    "彭埠站", "七堡站", "九和路站", "九堡站", "客运中心站", "下沙西站", "金沙湖站",
    # 2 号线
    "钱江路站", "庆春广场站", "建国北路站", "中河北路站", "沈塘桥站", "文新站", "丰潭路站", "古翠路站",
    # 3 号线
    "黄龙洞站", "松木场站", "武林门站", "西湖文化广场站", "潮鸣寺巷站", "建国南路站",
    # 4 号线
    "复兴路站", "南星桥站", "甬江路站", "城星路站", "市民中心站", "江锦路站", "景芳站", "新塘站",
    "火车东站站", "笕桥站",
    # 5 号线
    "大运河站", "拱宸桥东站", "善贤站", "宝善桥站", "万安桥站", "城站",
    # 6 号线
    "之江路站", "江汉路站", "长河站", "建业路站", "中医药大学站", "亚运村站",
    # 10 / 19 号线
    "文三路站", "学院路站", "翠柏路站", "黄龙体育中心站", "火车西站站",
]


def load_stations() -> dict[str, tuple[float, float]]:
    if CACHE.exists():
        data = json.loads(CACHE.read_text(encoding="utf-8"))
    else:
        data = {}
    changed = False
    for s in dict.fromkeys(STATIONS):
        if s in data:
            continue
        p = coords.poi_wgs84(s, "杭州")
        if p:
            data[s] = p
            changed = True
            print(f"  + {s} {p[1]:.4f},{p[0]:.4f}", flush=True)
    if changed:
        CACHE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return {k: tuple(v) for k, v in data.items()}


def restaurant_point(name: str, metro: str = "") -> tuple[float, float] | None:
    """先按店名找 POI；找不到就退到 metro 字段里的商场/路段名。"""
    p = coords.poi_wgs84(name, "杭州")
    if p:
        return p
    if metro:
        # 从「地铁 4 号线 江锦路站 步行约 0.9 km；上城区四季青街道森禾商务广场」里抽后半段地名
        tail = metro.split("；")[-1] if "；" in metro else metro
        for cand in [tail, tail.split("（")[0], tail.split(" ")[0]]:
            if len(cand) >= 4:
                p = coords.poi_wgs84(cand, "杭州")
                if p:
                    return p
    return None


def parking_near(name: str, point, limit_km: float = 0.8):
    """查停车场：店名 + 门牌/商圈 两种搜法，去重后按距离排。"""
    out = {}
    queries = [f"{name} 停车场", f"{name} 停车"]
    for q in queries:
        for h in coords.bd_poi(q, "杭州"):
            if "停车" not in (h["name"] or "") and "停车" not in (h["tag"] or ""):
                continue
            x = coords.bd09mc_to_bd09(*h["geo"])
            x = coords.bd09_to_gcj02(*x)
            wgs = coords.gcj02_to_wgs84(*x)
            d = coords.haversine(point, wgs)
            if d <= limit_km:
                out[h["name"]] = (round(d, 2), h["addr"])
    return sorted(((d, n, a) for n, (d, a) in out.items()))


def main():
    only = sys.argv[1:]
    import requests
    S = requests.Session(); S.trust_env = False
    menu = S.get("http://8.136.46.200:8000/api/date/menu", timeout=20).json()
    print(f"菜单 {len(menu)} 家\n站点缓存加载中…")
    stations = load_stations()
    print(f"站点 {len(stations)} 个\n")

    rows = []
    for it in menu:
        if only and not any(k in it["name"] for k in only):
            continue
        p = restaurant_point(it["name"], it.get("metro", ""))
        if not p:
            print(f"{it['name']}: 取不到坐标，跳过")
            continue
        near = sorted((coords.haversine(p, c), s) for s, c in stations.items())
        d, st = near[0]
        rows.append((d, st, it["name"], p, it))

    rows.sort(reverse=True)
    print(f"{'店名':20} {'最近站':10} {'直线':>6}  是否 >500m")
    for d, st, name, p, it in rows:
        flag = "★ 超过 500m" if d > 0.5 else ""
        print(f"{name[:18]:20} {st:10} {d*1000:5.0f}m  {flag}")

    far = [r for r in rows if r[0] > 0.5]
    print(f"\n===== 超过 500 m 的 {len(far)} 家，查停车场 =====")
    for d, st, name, p, it in far:
        print(f"\n{name}（最近地铁 {st} {d*1000:.0f} m）")
        spots = parking_near(name, p)
        if not spots:
            print("  800 m 内没搜到带「停车」的 POI —— 需要人工看地图")
            continue
        for dd, n, a in spots[:5]:
            print(f"  {dd*1000:4.0f} m  {n}  | {a}")


if __name__ == "__main__":
    main()
