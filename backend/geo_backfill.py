"""给 places 补坐标：百度 POI（免 key）+ 城市偏移修正。

为什么是百度：杭州本地小店在 OSM 里基本没有（27 家 0 命中），而百度有门店级 POI，
这个 JSONP 接口还不需要 key（仓库里 scripts/xhs_photos/coords.py 早就用它算「离家/离公司」）。

为什么还要修正：百度墨卡托按通用公式转成 WGS84 后，**整座城市纬度统一偏 -0.16856 度**
（约 18 km），经度只差 -0.00059（约 60 m）。不修的话，「走路 6 分钟」会变成「走路 4 小时」。
偏移量存在 data/geo_offset.json，是拿 11 个两源都查得到的地标比对 OSM 取中位数得到的
（离散度 ±100 m）。要重算就 `--recalibrate`（需要能连上 nominatim）。

为什么查不到时留空：没坐标的地点前端降级成「同区」、不写分钟。假精确比没数据更伤。

用法：
    cd backend
    python geo_backfill.py                # 补所有缺坐标的地点
    python geo_backfill.py --dry          # 只看查到什么，不写库
    python geo_backfill.py --only 叶马     # 只补名字里含这个词的
    python geo_backfill.py --refresh      # 忽略缓存重查
    python geo_backfill.py --recalibrate  # 重新标定城市偏移（需要 OSM 可达）

缓存：backend/data/geo_cache.json（重跑不重复请求）
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import statistics
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from sqlalchemy import select

import app.models  # noqa: F401
from app.database import Base, async_session, engine
from app.models.place import Place

HERE = Path(__file__).resolve().parent
CACHE = HERE / "data" / "geo_cache.json"
OFFSET = HERE / "data" / "geo_offset.json"
UA = "Mozilla/5.0 (selfsec place-geo)"
CITY = "杭州"
DISTRICTS = [
    "上城区", "拱墅区", "西湖区", "滨江区", "萧山区", "余杭区", "临平区",
    "钱塘区", "富阳区", "临安区", "桐庐县", "建德市", "淳安县",
]
# 标定用的地标：两个源都有，且东西南北散开
CALIB_POINTS = ["天目里", "灵隐寺", "吴山广场", "宝石山", "浙江美术馆", "湘湖", "良渚古城遗址公园", "南宋御街"]


# ── 网络：百度绕代理（走代理会返回 recaptcha），OSM 直连不通、要代理 ──
def _get(url: str, *, use_proxy: bool, timeout: int = 20) -> str:
    proxies = {k: v for k, v in urllib.request.getproxies().items()} if use_proxy else {}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler(proxies))
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with opener.open(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


# ── 百度墨卡托 → BD09 → GCJ02 → WGS84（与 scripts/xhs_photos/coords.py 同一套）──
def bd09mc_to_bd09(x: float, y: float) -> tuple[float, float]:
    lng = abs(x) / 20037508.34 * 180
    lat = abs(y) / 20037508.34 * 180
    lat = 180 / math.pi * (2 * math.atan(math.exp(lat * math.pi / 180)) - math.pi / 2)
    return lng, lat


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
    magic = 1 - ee * math.sin(radlat) ** 2
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrtmagic) * math.pi)
    dlng = (dlng * 180.0) / (a / sqrtmagic * math.cos(radlat) * math.pi)
    return lng - dlng, lat - dlat


def hav(a: tuple[float, float], b: tuple[float, float]) -> float:
    """两点距离（km），参数是 (lng, lat)。"""
    r = 6371.0
    lng1, lat1 = a
    lng2, lat2 = b
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lng2 - lng1)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _norm(text: str) -> str:
    return re.sub(r"[\s·・\-—_（）()]", "", (text or "")).lower()


# ── 两个源 ────────────────────────────────────────────────
def baidu_lookup(name: str, branch: str = "") -> dict | None:
    """查百度 POI。名字对不上就换短写法再试，全都对不上就返回 None。"""
    variants: list[str] = []
    for raw in (name, name.split("·")[0], re.split(r"[·\s]", name)[0]):
        q = _norm(raw)
        if q and q not in variants:
            variants.append(q)

    for variant in variants:
        url = (
            "https://map.baidu.com/?qt=s&wd="
            + urllib.parse.quote(f"{CITY}{variant}")
            + "&c=179&ie=utf-8&callback=cb&rn=10&pn=0"
        )
        try:
            raw = _get(url, use_proxy=False)
        except Exception as exc:
            print(f"    ! 百度请求失败：{exc}")
            return None
        start, end = raw.find("("), raw.rfind(")")
        if start < 0 or end < 0:
            continue
        try:
            data = json.loads(raw[start + 1:end])
        except Exception:
            continue

        hits = []
        for item in data.get("content") or []:
            if not isinstance(item, dict):
                continue  # content 里混着行政区聚簇（数组）
            nums = re.findall(r"-?\d+\.\d+", item.get("geo") or "")
            if len(nums) < 2:
                continue
            poi_name = item.get("name") or ""
            if variant not in _norm(poi_name):
                continue  # 名字对不上就不要，宁可留空
            lng, lat = bd09mc_to_bd09(float(nums[0]), float(nums[1]))
            lng, lat = bd09_to_gcj02(lng, lat)
            lng, lat = gcj02_to_wgs84(lng, lat)
            addr = item.get("addr") or ""
            hits.append(
                {
                    "lng": lng,
                    "lat": lat,
                    "area": next((d for d in DISTRICTS if d in addr), ""),
                    "address": addr[:255],
                    "matched": poi_name,
                }
            )
        if not hits:
            continue
        if branch:  # 有分店的，优先取地址里带分店关键词的那家
            key = _norm(branch).replace("店", "")
            for hit in hits:
                if key and key in _norm(hit["address"] + hit["matched"]):
                    return hit
        return hits[0]
    return None


def osm_lookup(name: str) -> dict | None:
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"format": "jsonv2", "limit": 1, "q": f"{name} {CITY}"}
    )
    try:
        rows = json.loads(_get(url, use_proxy=True))
    except Exception as exc:
        print(f"    ! OSM 请求失败：{exc}")
        return None
    if not rows:
        return None
    top = rows[0]
    display = top.get("display_name") or ""
    if CITY not in display:
        return None
    return {"lng": float(top["lon"]), "lat": float(top["lat"]), "matched": display.split(",")[0]}


def _load_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def recalibrate(cache: dict) -> dict:
    """用两源都有的地标重算城市偏移（中位数，抗个别错配）。"""
    pairs = []
    for name in CALIB_POINTS:
        b = baidu_lookup(name)
        time.sleep(0.4)
        o = osm_lookup(name)
        time.sleep(1.1)
        if b and o:
            pairs.append((b, o))
            print(f"  校准点 {name:<10} 百度 {b['lat']:.4f} → OSM {o['lat']:.4f}")
    dlat = [o["lat"] - b["lat"] for b, o in pairs if abs(o["lat"] - b["lat"]) < 1.0]
    dlng = [o["lng"] - b["lng"] for b, o in pairs if abs(o["lng"] - b["lng"]) < 1.0]
    if len(dlat) < 3:
        raise SystemExit("标定失败：两个源都能查到的地标不足 3 个（OSM 可能被限流）")
    out = {
        "_note": "百度坐标转 WGS84 后的城市统一偏移，用法见 geo_backfill.py",
        "lat": round(statistics.median(dlat), 6),
        "lng": round(statistics.median(dlng), 6),
        "n": len(dlat),
        "city": CITY,
        "derived_at": time.strftime("%Y-%m-%d"),
    }
    _save_json(OFFSET, out)
    return out


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry", action="store_true", help="只打印，不写库")
    parser.add_argument("--only", default="", help="只处理名字包含这个词的地点")
    parser.add_argument("--refresh", action="store_true", help="忽略缓存重新查")
    parser.add_argument("--recalibrate", action="store_true", help="重新标定城市偏移")
    args = parser.parse_args()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    if args.recalibrate:
        print("重新标定城市偏移：")
        off = recalibrate(_load_json(CACHE))
    else:
        off = _load_json(OFFSET)
        if not off.get("lat"):
            raise SystemExit(
                "缺少 data/geo_offset.json。先跑 python geo_backfill.py --recalibrate"
                "（需要能访问 nominatim.openstreetmap.org）"
            )
    print(
        f"城市偏移：Δlat {off['lat']:+.5f}  Δlng {off['lng']:+.5f}"
        f"（{off.get('n', '?')} 个地标标定，{off.get('derived_at', '?')}）\n"
    )

    cache = {} if args.refresh else _load_json(CACHE)
    async with async_session() as db:
        stmt = select(Place).where(Place.status == "active")
        if args.only:
            stmt = stmt.where(Place.name.like(f"%{args.only}%"))
        places = (await db.execute(stmt.order_by(Place.category, Place.name))).scalars().all()
        todo = [p for p in places if not p.has_geo]
        print(f"共 {len(places)} 个地点，缺坐标 {len(todo)} 个\n")

        filled = 0
        for place in todo:
            key = f"baidu|{place.name}|{place.branch}"
            hit = cache.get(key) if not args.refresh else None
            if hit is None:
                hit = baidu_lookup(place.name, place.branch)
                cache[key] = hit
                time.sleep(0.5)
            if not hit:
                print(f"  ✗ {place.name:<18} 没查到 → 留空（前端降级为「同区」）")
                continue
            lat, lng = hit["lat"] + off["lat"], hit["lng"] + off["lng"]
            print(
                f"  ✓ {place.name:<18} {lat:.5f},{lng:.5f}  "
                f"{place.area or hit['area'] or '?'}  ← {hit['matched'][:22]}"
            )
            if args.dry:
                continue
            place.lat, place.lng = round(lat, 6), round(lng, 6)
            place.area = place.area or hit["area"]
            place.address = place.address or hit["address"]
            filled += 1

        if not args.dry:
            await db.commit()
        _save_json(CACHE, cache)
    await engine.dispose()
    print(f"\n写入 {filled} 个。缓存：{CACHE}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    asyncio.run(main())
