"""地图文件格式：一个 GeoJSON 地物集合，坐标已经投影成米。

{
  "type": "FeatureCollection",
  "smartkeeper": {"format": "smartkeeper.map", "format_version": 1, "id": ..., "name": ...,
                  "origin": {"lon": ..., "lat": ...}, "bounds": [minx, miny, maxx, maxy],
                  "attribution": "© OpenStreetMap contributors"},
  "features": [
    {"type": "Feature", "id": "bldg_123",
     "properties": {"kind": "building", "name": "...", "height": 30, "min_height": 0},
     "geometry": {"type": "Polygon", "coordinates": [[[x, y], ...], ...]}}
  ]
}
"""

from __future__ import annotations

import json
from typing import Any, cast

from shapely.geometry import LineString, Polygon

from smartkeeper.contracts import (
    MapData,
    MapFeature,
    MapOrigin,
    Problem,
    ValidationFailed,
)
from smartkeeper.mapdata.projection import to_lonlat

FORMAT = "smartkeeper.map"
FORMAT_VERSION = 1
KINDS = ("building", "road", "park", "water", "landmark")


def _ring(raw: Any) -> tuple[tuple[float, float], ...]:
    return tuple((float(p[0]), float(p[1])) for p in raw)


def parse_map(text: str) -> MapData:
    """解析并校验地图文件。不合法时抛 ValidationFailed。"""
    try:
        body: Any = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValidationFailed("map.not_json", line=e.lineno) from e
    if not isinstance(body, dict):
        raise ValidationFailed("map.not_feature_collection")
    doc = cast(dict[str, Any], body)
    if doc.get("type") != "FeatureCollection":
        raise ValidationFailed("map.not_feature_collection")
    meta = doc.get("smartkeeper")
    if not isinstance(meta, dict):
        raise ValidationFailed("map.missing_meta")
    meta = cast(dict[str, Any], meta)
    if meta.get("format") != FORMAT or meta.get("format_version") != FORMAT_VERSION:
        raise ValidationFailed("map.bad_format")
    problems: list[Problem] = []
    features: list[MapFeature] = []
    seen: set[str] = set()
    for i, raw in enumerate(cast(list[Any], doc.get("features") or [])):
        path = f"features[{i}]"
        try:
            f = _feature(cast(dict[str, Any], raw))
        except (KeyError, TypeError, ValueError, IndexError):
            problems.append(Problem(code="map.bad_feature", path=path))
            continue
        if f.id in seen:
            problems.append(Problem(code="map.duplicate_id", path=path, params={"id": f.id}))
        seen.add(f.id)
        problems += _check_feature(f, path)
        features.append(f)
    if problems:
        raise ValidationFailed("map.invalid", problems)
    try:
        origin = MapOrigin(lon=float(meta["origin"]["lon"]), lat=float(meta["origin"]["lat"]))
        b = [float(x) for x in meta["bounds"]]
        bounds = (b[0], b[1], b[2], b[3])
    except (KeyError, TypeError, ValueError, IndexError) as e:
        raise ValidationFailed("map.bad_meta") from e
    return MapData(
        id=str(meta.get("id", "")),
        name=str(meta.get("name", "")),
        origin=origin,
        bounds=bounds,
        features=tuple(features),
        attribution=str(meta.get("attribution", "© OpenStreetMap contributors")),
    )


def _feature(raw: dict[str, Any]) -> MapFeature:
    props = cast(dict[str, Any], raw.get("properties") or {})
    geom = cast(dict[str, Any], raw["geometry"])
    kind = props["kind"]
    gtype = geom["type"]
    coords = geom["coordinates"]
    polygon = line = point = None
    if gtype == "Polygon":
        polygon = tuple(_ring(r) for r in coords)
    elif gtype == "LineString":
        line = _ring(coords)
    elif gtype == "Point":
        point = (float(coords[0]), float(coords[1]))
    else:
        raise ValueError(gtype)
    return MapFeature(
        id=str(raw["id"]),
        kind=kind,
        name=str(props.get("name", "")),
        polygon=polygon,
        line=line,
        point=point,
        height=float(props.get("height", 0.0)),
        min_height=float(props.get("min_height", 0.0)),
    )


def _check_feature(f: MapFeature, path: str) -> list[Problem]:
    problems: list[Problem] = []
    if f.kind not in KINDS:
        problems.append(Problem(code="map.bad_kind", path=path, params={"kind": f.kind}))
    if f.kind == "building":
        if f.polygon is None:
            problems.append(Problem(code="map.building_needs_polygon", path=path))
        if not f.height > f.min_height >= -1000:
            problems.append(Problem(code="map.bad_height", path=path, params={"id": f.id}))
    if f.polygon is not None:
        if len(f.polygon[0]) < 4:
            problems.append(Problem(code="map.bad_polygon", path=path, params={"id": f.id}))
        elif not Polygon(f.polygon[0], f.polygon[1:]).is_valid:
            problems.append(Problem(code="map.invalid_polygon", path=path, params={"id": f.id}))
    if f.line is not None and (len(f.line) < 2 or LineString(f.line).length == 0):
        problems.append(Problem(code="map.bad_line", path=path, params={"id": f.id}))
    return problems


def dump_map(m: MapData) -> str:
    feats: list[dict[str, Any]] = []
    for f in m.features:
        if f.polygon is not None:
            geom: dict[str, Any] = {
                "type": "Polygon",
                "coordinates": [[list(p) for p in r] for r in f.polygon],
            }
        elif f.line is not None:
            geom = {"type": "LineString", "coordinates": [list(p) for p in f.line]}
        else:
            assert f.point is not None
            geom = {"type": "Point", "coordinates": list(f.point)}
        props: dict[str, Any] = {"kind": f.kind, "name": f.name}
        if f.kind == "building":
            props["height"] = round(f.height, 2)
            props["min_height"] = round(f.min_height, 2)
        feats.append({"type": "Feature", "id": f.id, "properties": props, "geometry": geom})
    body = {
        "type": "FeatureCollection",
        "smartkeeper": {
            "format": FORMAT,
            "format_version": FORMAT_VERSION,
            "id": m.id,
            "name": m.name,
            "origin": {"lon": m.origin.lon, "lat": m.origin.lat},
            "bounds": list(m.bounds),
            "attribution": m.attribution,
        },
        "features": feats,
    }
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"))


def display_geojson(m: MapData) -> dict[str, Any]:
    """给地图组件用的经纬度 GeoJSON（MapLibre 只认经纬度）。"""
    lon0, lat0 = m.origin.lon, m.origin.lat

    def ll(p: tuple[float, float]) -> list[float]:
        lon, lat = to_lonlat(lon0, lat0, p[0], p[1])
        return [round(lon, 7), round(lat, 7)]

    feats: list[dict[str, Any]] = []
    for f in m.features:
        if f.polygon is not None:
            geom: dict[str, Any] = {
                "type": "Polygon",
                "coordinates": [[ll(p) for p in r] for r in f.polygon],
            }
        elif f.line is not None:
            geom = {"type": "LineString", "coordinates": [ll(p) for p in f.line]}
        else:
            assert f.point is not None
            geom = {"type": "Point", "coordinates": ll(f.point)}
        feats.append(
            {
                "type": "Feature",
                "id": f.id,
                "properties": {
                    "id": f.id,
                    "kind": f.kind,
                    "name": f.name,
                    "height": f.height,
                    "min_height": f.min_height,
                },
                "geometry": geom,
            }
        )
    minx, miny, maxx, maxy = m.bounds
    sw = to_lonlat(lon0, lat0, minx, miny)
    ne = to_lonlat(lon0, lat0, maxx, maxy)
    return {
        "type": "FeatureCollection",
        "features": feats,
        "id": m.id,
        "name": m.name,
        "origin": {"lon": lon0, "lat": lat0},
        "bounds_lonlat": [sw[0], sw[1], ne[0], ne[1]],
        "attribution": m.attribution,
    }
