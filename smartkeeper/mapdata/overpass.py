"""Overpass API 的地址和查询。"""

from __future__ import annotations

OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
)


def overpass_query(s: float, w: float, n: float, e: float) -> str:
    bb = f"({s},{w},{n},{e})"
    return f"""[out:json][timeout:300];
(
  way["building"]{bb};
  way["highway"]{bb};
  way["leisure"~"^(park|garden)$"]{bb};
  way["landuse"~"^(grass|recreation_ground|reservoir)$"]{bb};
  way["natural"="water"]{bb};
  way["waterway"="riverbank"]{bb};
  node["name"]["tourism"]{bb};
  node["name"]["historic"]{bb};
  node["name"]["railway"="station"]{bb};
);
out geom;"""
