"""按行政区导入：取几个区的边界，分块下载区域内的数据，只保留落在这些区里的地物。

uv run python -m smartkeeper.mapdata --areas 港区,渋谷区,新宿区 --within 東京都 --id tokyo3 --name "港区·涩谷区·新宿区"
"""

from __future__ import annotations

import sys
import time
from collections.abc import Sequence
from typing import Any, cast

import httpx
from shapely.geometry import LineString
from shapely.geometry.base import BaseGeometry
from shapely.ops import polygonize, unary_union

from smartkeeper.mapdata.overpass import overpass_query


def _post(query: str, urls: Sequence[str], tries: int = 3) -> dict[str, Any]:
    last: Exception | None = None
    for attempt in range(tries):
        for url in urls:
            try:
                resp = httpx.post(
                    url,
                    data={"data": query},
                    headers={"User-Agent": "SmartKeeper-map-importer/0.1"},
                    timeout=400,
                )
                resp.raise_for_status()
                return cast(dict[str, Any], resp.json())
            except (httpx.HTTPError, ValueError) as err:
                print(f"overpass {url} failed: {err}", file=sys.stderr)
                last = err
        time.sleep(10 * (attempt + 1))
    assert last is not None
    raise last


def fetch_boundaries(
    names: Sequence[str], within: str, urls: Sequence[str], admin_level: int = 7
) -> BaseGeometry:
    """行政区边界的并集（经纬度）。"""
    pattern = "|".join(names)
    query = f"""[out:json][timeout:180];
area["name"="{within}"]["boundary"="administrative"]->.outer;
relation["boundary"="administrative"]["admin_level"="{admin_level}"]["name"~"^({pattern})$"](area.outer);
out geom;"""
    data = _post(query, urls)
    polys: list[BaseGeometry] = []
    found: list[str] = []
    for rel in cast(list[dict[str, Any]], data.get("elements", [])):
        lines = [
            LineString([(p["lon"], p["lat"]) for p in m["geometry"]])
            for m in cast(list[dict[str, Any]], rel.get("members", []))
            if m.get("type") == "way"
            and m.get("role") in ("outer", "")
            and len(m.get("geometry") or []) >= 2
        ]
        parts = list(polygonize(lines))
        if parts:
            polys.append(unary_union(parts))
            found.append(str(cast(dict[str, Any], rel.get("tags", {})).get("name")))
    missing = set(names) - set(found)
    if missing:
        raise RuntimeError(f"boundaries not found: {sorted(missing)}")
    print(f"boundaries: {found}", file=sys.stderr)
    return unary_union(polys)


def fetch_tiled(
    bbox: tuple[float, float, float, float], step: float, urls: Sequence[str]
) -> dict[str, Any]:
    """把 bbox 切成 step 度的小块分别下载，按元素 id 去重后合并。"""
    s, w, n, e = bbox
    seen: set[tuple[str, int]] = set()
    elements: list[dict[str, Any]] = []
    lat = s
    tiles = 0
    while lat < n:
        lon = w
        while lon < e:
            tiles += 1
            box = (lat, lon, min(lat + step, n), min(lon + step, e))
            data = _post(overpass_query(*box), urls)
            got = cast(list[dict[str, Any]], data.get("elements", []))
            for el in got:
                key = (str(el.get("type")), int(el.get("id", 0)))
                if key not in seen:
                    seen.add(key)
                    elements.append(el)
            print(f"tile {tiles}: {box} +{len(got)} -> {len(elements)}", file=sys.stderr)
            lon += step
        lat += step
    return {"elements": elements}
