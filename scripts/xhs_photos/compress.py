"""把抓下来的图压一压再上线：手机页面上一次铺 22 张封面，原图 300KB 太重。

- 最长边缩到 960，WebP quality 74
- 宽高原样写回 out/<slug>.json（前台靠这个比例占位，压完比例不变）
"""
import json
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
MAXW = 960
Q = 74

total_before = total_after = 0
for f in sorted(OUT.glob("r*.json")):
    rec = json.loads(f.read_text(encoding="utf-8"))
    for p in rec["photos"]:
        fp = Path(p["file"])
        if not fp.exists():
            continue
        before = fp.stat().st_size
        with Image.open(fp) as im:
            im = im.convert("RGB")
            if im.width > MAXW:
                im = im.resize((MAXW, round(im.height * MAXW / im.width)), Image.LANCZOS)
            tmp = fp.with_suffix(".tmp.webp")
            im.save(tmp, "WEBP", quality=Q, method=6)
            p["w"], p["h"] = im.size
        tmp.replace(fp)
        after = fp.stat().st_size
        total_before += before
        total_after += after
    f.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{f.name}: {len(rec['photos'])} 张")

print(f"合计 {total_before/1e6:.1f} MB → {total_after/1e6:.1f} MB")
