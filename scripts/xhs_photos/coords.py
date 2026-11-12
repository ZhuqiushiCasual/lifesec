"""取 POI 坐标并算「离家 / 离公司」直线距离（百度地图 JSONP 接口，无需 key）。

先校准锚点：用菜单里已有的几条（dist_km / dist_work_km 都是现成的）反查，
只有复现误差 ≤0.15 km 才用它算新店；对不上就说明锚点取错点位了。

用法： python coords.py 宽马记大排档 一恒一素 ...
"""
import json
import math
import re
import subprocess
import sys
import urllib.parse

CITY = "杭州"


def bd_poi(name: str, region: str = "") -> list[dict]:
    q = urllib.parse.quote(f"{region}{name}".strip())
    url = f"https://map.baidu.com/?qt=s&wd={q}&c=179&ie=utf-8&callback=cb&rn=10&pn=0"
    out = subprocess.run(["curl", "-s", "--noproxy", "*", "--max-time", "20", url],
                         capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    m = out.find("(")
    if m < 0:
        return []
    try:
        data = json.loads(out[m + 1: out.rfind(")")])
    except Exception:
        return []
    res = []
    for it in (data.get("content") or []):
        if not isinstance(it, dict):        # content 里混着数组（行政区聚簇），跳过
            continue
        geo = it.get("geo") or ""
        # 百度 geo 形如 "1|13384144.45,4825923.95"：前面还带个点位类型标记，别整体 float
        nums = re.findall(r"-?\d+\.\d+", geo)
        if len(nums) < 2:
            continue
        res.append({"name": it.get("name"), "addr": it.get("addr"),
                    "geo": (float(nums[0]), float(nums[1])),
                    "tag": it.get("std_tag") or ""})
    return res


# ── BD09MC → WGS84（百度墨卡托 → 百度经纬 → 火星 → WGS84）──
def bd09mc_to_bd09(x: float, y: float) -> tuple[float, float]:
    x = abs(x) / 20037508.34 * 180
    y = y / 20037508.34 * 180
    y = 180 / math.pi * (2 * math.atan(math.exp(y * math.pi / 180)) - math.pi / 2)
    return x, y


def bd09_to_gcj02(lng: float, lat: float) -> tuple[float, float]:
    x_pi = math.pi * 3000.0 / 180.0
    x, y = lng - 0.0065, lat - 0.006
    z = math.sqrt(x * x + y * y) - 0.00002 * math.sin(y * x_pi)
    theta = math.atan2(y, x) - 0.000003 * math.cos(x * x_pi)
    return z * math.cos(theta), z * math.sin(theta)


def gcj02_to_wgs84(lng: float, lat: float) -> tuple[float, float]:
    a = 6378245.0
    ee = 0.00669342162296594323

    def out_of_china(lng, lat):
        return not (73.66 < lng < 135.05 and 3.86 < lat < 53.55)

    def transform_lat(x, y):
        ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
        ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
        ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
        ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
        return ret

    def transform_lng(x, y):
        ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
        ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
        ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
        ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
        return ret

    if out_of_china(lng, lat):
        return lng, lat
    dlat = transform_lat(lng - 105.0, lat - 35.0)
    dlng = transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * math.pi
    magic = math.sin(radlat)
    magic = 1 - ee * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrtmagic) * math.pi)
    dlng = (dlng * 180.0) / (a / sqrtmagic * math.cos(radlat) * math.pi)
    return lng - dlng, lat - dlat


def poi_wgs84(name: str, region: str = "") -> tuple[float, float] | None:
    hits = bd_poi(name, region)
    if not hits:
        return None
    x, y = hits[0]["geo"]
    lng, lat = bd09mc_to_bd09(x, y)
    lng, lat = bd09_to_gcj02(lng, lat)
    return gcj02_to_wgs84(lng, lat)


def haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
    R = 6371.0
    lng1, lat1 = a
    lng2, lat2 = b
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


# 校准用：菜单里现成的「离家 / 离公司」（见 services/date_menu.py 的 SEED）
CHECK = {
    "梅溪徐记 德信中心": (0.17, 9.08),
    "寿司郎 黄龙": (9.28, 1.77),
    "庆春里 嘉里中心": (6.78, 2.85),
    "禧粤鱼捞 亚奥万象天地": (4.85, 11.03),
}


def solve_anchor(points: list[tuple[tuple[float, float], float]], guess: tuple[float, float]):
    """用「已知坐标的点 + 菜单里写死的距离」反解锚点。

    百度 POI 点位和菜单当初用的锚点不一定同一个点（三花国际 vs 彭埠站 A 口差 0.1 km 级别），
    直接拿 POI 算会整体偏。这里以 POI 为初值做网格搜索，让 4 条已知记录的距离误差最小。
    """
    best, best_err = guess, 1e9
    span, step = 0.02, 0.002
    for _ in range(3):
        lng0, lat0 = best
        lng, lat = lng0 - span, lat0 - span
        while lng <= lng0 + span:
            la = lat0 - span
            while la <= lat0 + span:
                err = sum((haversine((lng, la), p) - d) ** 2 for p, d in points)
                if err < best_err:
                    best_err, best = err, (lng, la)
                la += step
            lng += step
        span, step = step, step / 5
    return best, math.sqrt(best_err / len(points))


def main():
    home0 = poi_wgs84("三花国际", CITY)
    work0 = poi_wgs84("黄龙体育中心", CITY)
    print("POI 原始：家", home0, " 公司", work0)

    home_pts, work_pts = [], []
    print("\n校准点（书面距离 vs POI 直接算）:")
    for name, (d_home, d_work) in CHECK.items():
        p = poi_wgs84(name, CITY)
        if not p:
            print(f"  {name}: 取不到坐标")
            continue
        print(f"  {name}: 家 {d_home} / 算 {haversine(home0, p):.2f} | 公司 {d_work} / 算 {haversine(work0, p):.2f}")
        home_pts.append((p, d_home))
        work_pts.append((p, d_work))

    home, err_h = solve_anchor(home_pts, home0)
    work, err_w = solve_anchor(work_pts, work0)
    print(f"\n反解锚点：家 {home} (残差 {err_h:.2f} km)  公司 {work} (残差 {err_w:.2f} km)")
    for name, (d_home, d_work) in CHECK.items():
        p = poi_wgs84(name, CITY)
        if p:
            print(f"  校验 {name}: 家 {haversine(home, p):.2f}(书面 {d_home}) 公司 {haversine(work, p):.2f}(书面 {d_work})")

    for name in sys.argv[1:]:
        p = poi_wgs84(name, CITY)
        hits = bd_poi(name, CITY)[:3]
        if not p:
            print(f"\n{name}: 取不到坐标；候选 {[h['name'] for h in hits]}")
            continue
        print(f"\n{name}")
        print(f"  坐标 {p[1]:.5f},{p[0]:.5f}  离家 {haversine(home, p):.2f} km  离公司 {haversine(work, p):.2f} km")
        for h in hits:
            print(f"  候选: {h['name']} | {h['addr']} | {h['tag']}")


if __name__ == "__main__":
    main()
