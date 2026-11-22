"""从导入好的地图文件生成地图组件静态演示页用的假数据（经纬度 GeoJSON）。

uv run python scripts/make_demo_map.py maps/demo_shibuya.geojson frontend/demo/demo-map.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from smartkeeper.mapdata import display_geojson, parse_map


def main() -> int:
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    m = parse_map(src.read_text(encoding="utf-8"))
    out.write_text(
        json.dumps(display_geojson(m), ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    print(f"{out}: {len(m.features)} features")
    return 0


if __name__ == "__main__":
    sys.exit(main())
