import sys
sys.argv = ["x"]
import coords, json

TARGETS = [
    ("宽马记大排档", "森禾商务广场 杭州"),
    ("虾佬九", "西湖文化广场 杭州"),
    ("泥靴 City", "平安悦坊 杭州"),
    ("丹粤阁", "清泰街456号 杭州"),
    ("一恒一素", "小河路368号 杭州"),
    ("微风山丘", "滨江星光大道 杭州"),
    ("Luback Dining", "越王路2077号 杭州"),
]

for name, landmark in TARGETS:
    p = coords.poi_wgs84(landmark, "杭州")
    print(f"\n=== {name}  @ {landmark} {'→ ' + f'{p[1]:.4f},{p[0]:.4f}' if p else '（取不到坐标）'}")
    if not p:
        continue
    seen = {}
    for q in [landmark + " 停车场", landmark + " 停车", landmark.split()[0] + " 停车场"]:
        for h in coords.bd_poi(q, "杭州"):
            if "停车" not in (h["name"] or "") and "停车" not in (h["tag"] or ""):
                continue
            x = coords.bd09mc_to_bd09(*h["geo"]); x = coords.bd09_to_gcj02(*x); wgs = coords.gcj02_to_wgs84(*x)
            d = coords.haversine(p, wgs)
            if d <= 0.9 and h["name"] not in seen:
                seen[h["name"]] = (d, h["addr"])
    for n, (d, a) in sorted(seen.items(), key=lambda kv: kv[1][0])[:8]:
        print(f"   {d*1000:4.0f} m  {n[:38]:40} | {a[:46]}")
    if not seen:
        print("   （900 m 内无「停车」POI）")
