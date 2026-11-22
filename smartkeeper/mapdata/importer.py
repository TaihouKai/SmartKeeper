"""离线导入工具：OpenStreetMap（Overpass JSON）→ 地图文件。

    uv run python -m smartkeeper.mapdata --bbox 35.655,139.695,35.665,139.705 --id demo --name Demo
    uv run python -m smartkeeper.mapdata --overpass-file export.json --id demo --name Demo

运行时只读导出的地图文件，不联网；联网只发生在这个工具里（从 Overpass 下载导出数据）。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from shapely.geometry import LineString, Polygon
from shapely.validation import make_valid

from smartkeeper.contracts import FeatureKind, MapData, MapFeature, MapOrigin
from smartkeeper.mapdata.fileformat import dump_map
from smartkeeper.mapdata.heights import DEFAULT_HEIGHTS, building_height, building_min_height
from smartkeeper.mapdata.projection import to_meters

OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
)
ROAD_TYPES = {
    "motorway",
    "trunk",
    "primary",
    "secondary",
    "tertiary",
    "unclassified",
    "residential",
    "living_street",
    "pedestrian",
    "motorway_link",
    "trunk_link",
    "primary_link",
    "secondary_link",
    "tertiary_link",
}
PARK_TAGS = {
    ("leisure", "park"),
    ("leisure", "garden"),
    ("landuse", "grass"),
    ("landuse", "recreation_ground"),
}
WATER_TAGS = {("natural", "water"), ("waterway", "riverbank"), ("landuse", "reservoir")}
LANDMARK_KEYS = ("tourism", "historic", "amenity", "railway", "public_transport")


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


def fetch_overpass(
    s: float, w: float, n: float, e: float, urls: Sequence[str] = OVERPASS_URLS
) -> dict[str, Any]:
    """依次尝试几个 Overpass 镜像。"""
    import httpx

    last: Exception | None = None
    for url in urls:
        try:
            resp = httpx.post(
                url,
                data={"data": overpass_query(s, w, n, e)},
                headers={"User-Agent": "SmartKeeper-map-importer/0.1"},
                timeout=360,
            )
            resp.raise_for_status()
            return cast(dict[str, Any], resp.json())
        except (httpx.HTTPError, ValueError) as err:
            print(f"overpass {url} failed: {err}", file=sys.stderr)
            last = err
    assert last is not None
    raise last


def _kind(tags: Mapping[str, str]) -> FeatureKind | None:
    if "building" in tags:
        return "building"
    if tags.get("highway") in ROAD_TYPES:
        return "road"
    if any(tags.get(k) == v for k, v in PARK_TAGS):
        return "park"
    if any(tags.get(k) == v for k, v in WATER_TAGS):
        return "water"
    return None


def convert(
    data: Mapping[str, Any],
    *,
    map_id: str,
    name: str,
    bbox: tuple[float, float, float, float] | None = None,
    defaults: Mapping[str, float] = DEFAULT_HEIGHTS,
) -> MapData:
    """把 Overpass 的 `out geom` 结果转成地图。bbox = (south, west, north, east)。"""
    elements = cast(list[dict[str, Any]], data.get("elements", []))
    if bbox is None:
        lats = [p["lat"] for el in elements for p in el.get("geometry", [])] + [
            el["lat"] for el in elements if el.get("type") == "node"
        ]
        lons = [p["lon"] for el in elements for p in el.get("geometry", [])] + [
            el["lon"] for el in elements if el.get("type") == "node"
        ]
        if not lats:
            raise ValueError("no elements")
        bbox = (min(lats), min(lons), max(lats), max(lons))
    s, w, n, e = bbox
    lat0, lon0 = (s + n) / 2, (w + e) / 2

    def m(lon: float, lat: float) -> tuple[float, float]:
        x, y = to_meters(lon0, lat0, lon, lat)
        return round(x, 2), round(y, 2)

    corners = [m(w, s), m(e, s), m(w, n), m(e, n)]
    bounds = (
        min(c[0] for c in corners),
        min(c[1] for c in corners),
        max(c[0] for c in corners),
        max(c[1] for c in corners),
    )
    features: list[MapFeature] = []
    for el in elements:
        tags = cast(dict[str, str], el.get("tags") or {})
        if el.get("type") == "node":
            if "name" in tags and any(k in tags for k in LANDMARK_KEYS):
                features.append(
                    MapFeature(
                        id=f"lm_{el['id']}",
                        kind="landmark",
                        name=tags["name"],
                        point=m(el["lon"], el["lat"]),
                    )
                )
            continue
        if el.get("type") != "way":
            continue
        kind = _kind(tags)
        geom = cast(list[dict[str, float]], el.get("geometry") or [])
        if kind is None or len(geom) < 2:
            continue
        pts = tuple(m(p["lon"], p["lat"]) for p in geom)
        fid = {"building": "bldg", "road": "road", "park": "park", "water": "water"}[
            kind
        ] + f"_{el['id']}"
        label = tags.get("name", "")
        if kind == "road":
            if LineString(pts).length > 0:
                features.append(MapFeature(id=fid, kind="road", name=label, line=pts))
            continue
        if len(pts) < 4 or pts[0] != pts[-1]:
            continue
        poly = Polygon(pts)
        if not poly.is_valid:
            fixed = make_valid(poly)
            if not isinstance(fixed, Polygon):
                continue
            poly = fixed
        if poly.area < 1.0:
            continue
        ring = tuple((round(x, 2), round(y, 2)) for x, y in poly.exterior.coords)
        if kind == "building":
            h = building_height(tags, defaults)
            mh = min(building_min_height(tags), h - 0.5)
            features.append(
                MapFeature(
                    id=fid,
                    kind="building",
                    name=label,
                    polygon=(ring,),
                    height=h,
                    min_height=max(mh, 0.0),
                )
            )
        else:
            features.append(MapFeature(id=fid, kind=kind, name=label, polygon=(ring,)))
    return MapData(
        id=map_id,
        name=name,
        origin=MapOrigin(lon=lon0, lat=lat0),
        bounds=bounds,
        features=tuple(features),
    )


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--bbox", help="south,west,north,east（经纬度）")
    ap.add_argument("--overpass-file", help="已下载的 Overpass JSON（out geom）")
    ap.add_argument("--id", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--out", help="输出路径，默认 maps/<id>.geojson")
    ap.add_argument("--defaults", help="建筑默认高度的 JSON 配置 {building 类型: 米}")
    ap.add_argument("--save-raw", help="把下载到的 Overpass JSON 另存一份")
    ap.add_argument(
        "--overpass-url", action="append", help="Overpass 服务地址，可重复；默认依次试几个公共镜像"
    )
    args = ap.parse_args(argv)
    bbox: tuple[float, float, float, float] | None = None
    if args.bbox:
        parts = [float(x) for x in args.bbox.split(",")]
        if len(parts) != 4:
            ap.error("--bbox needs 4 numbers")
        bbox = (parts[0], parts[1], parts[2], parts[3])
    defaults: dict[str, float] = dict(DEFAULT_HEIGHTS)
    if args.defaults:
        defaults.update(json.loads(Path(args.defaults).read_text(encoding="utf-8")))
    if args.overpass_file:
        data = json.loads(Path(args.overpass_file).read_text(encoding="utf-8"))
    elif bbox is not None:
        data = fetch_overpass(*bbox, urls=args.overpass_url or OVERPASS_URLS)
        if args.save_raw:
            Path(args.save_raw).write_text(json.dumps(data), encoding="utf-8")
    else:
        ap.error("need --bbox or --overpass-file")
    result = convert(data, map_id=args.id, name=args.name, bbox=bbox, defaults=defaults)
    out = Path(args.out or f"maps/{args.id}.geojson")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(dump_map(result), encoding="utf-8")
    counts: dict[str, int] = {}
    for f in result.features:
        counts[f.kind] = counts.get(f.kind, 0) + 1
    print(json.dumps({"out": str(out), "features": counts}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
