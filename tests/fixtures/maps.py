"""手写的小地图（米制坐标），只用 contracts 构造，不依赖 mapdata。"""

from __future__ import annotations

from smartkeeper.contracts import MapData, MapFeature, MapOrigin


def square(x0: float, y0: float, x1: float, y1: float) -> tuple[tuple[tuple[float, float], ...]]:
    return (((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)),)


def small_map() -> MapData:
    return MapData(
        id="small",
        name="Small",
        origin=MapOrigin(lon=139.7, lat=35.66),
        bounds=(-100.0, -100.0, 200.0, 200.0),
        features=(
            MapFeature(
                id="bldg_tower",
                kind="building",
                name="Tower",
                polygon=square(0, 0, 20, 20),
                height=30,
            ),
            MapFeature(
                id="bldg_low",
                kind="building",
                name="Low House",
                polygon=square(40, 0, 60, 20),
                height=10,
            ),
            MapFeature(
                id="bldg_float",
                kind="building",
                name="Skybridge",
                polygon=square(80, 0, 90, 20),
                height=40,
                min_height=20,
            ),
            MapFeature(
                id="road_main", kind="road", name="Main Street", line=((-100, -10), (200, -10))
            ),
            MapFeature(
                id="park_green", kind="park", name="Green Park", polygon=square(0, 50, 50, 100)
            ),
            MapFeature(id="lm_clock", kind="landmark", name="Clock", point=(25.0, 75.0)),
        ),
    )
