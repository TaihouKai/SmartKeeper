"""mapdata 的单独测试：几栋建筑的样例数据，不导入 eventlog、world、kp、web。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from smartkeeper.contracts import ValidationFailed
from smartkeeper.mapdata import (
    FileMapStore,
    building_height,
    building_min_height,
    convert,
    display_geojson,
    dump_map,
    floor_z,
    parse_map,
    to_lonlat,
    to_meters,
)

LON0, LAT0 = 139.70, 35.66


def test_height_rules() -> None:
    assert building_height({"building": "yes", "height": "42.5"}) == 42.5
    assert building_height({"building": "yes", "height": "12 m", "building:levels": "9"}) == 12
    assert building_height({"building": "yes", "building:levels": "7"}) == 21
    assert building_height({"building": "house"}) == 6
    assert building_height({"building": "nonsense"}) == 9
    assert building_height({"building": "office"}, {"office": 50, "default": 1}) == 50
    assert building_height({"building": "yes", "height": "junk", "building:levels": "2"}) == 6
    assert building_min_height({"min_height": "20"}) == 20
    assert building_min_height({"building:min_level": "3"}) == 9
    assert building_min_height({}) == 0


def test_floor_z() -> None:
    assert floor_z(1) == 0
    assert floor_z(5) == 12
    assert floor_z(-1) == -3


@given(st.floats(-0.04, 0.04), st.floats(-0.04, 0.04))
def test_projection_roundtrip_under_1m(dlon: float, dlat: float) -> None:
    lon, lat = LON0 + dlon, LAT0 + dlat
    x, y = to_meters(LON0, LAT0, lon, lat)
    lon2, lat2 = to_lonlat(LON0, LAT0, x, y)
    x2, y2 = to_meters(LON0, LAT0, lon2, lat2)
    assert abs(x - x2) < 1 and abs(y - y2) < 1
    assert abs(lon - lon2) * 90000 < 1 and abs(lat - lat2) * 111000 < 1


def test_projection_axes() -> None:
    x, y = to_meters(LON0, LAT0, LON0 + 0.01, LAT0)
    assert 890 < x < 920 and abs(y) < 5  # 向东约 900 米
    x, y = to_meters(LON0, LAT0, LON0, LAT0 + 0.01)
    assert abs(x) < 1 and 1100 < y < 1120  # 向北约 1110 米


def way(id: int, tags: dict[str, str], pts: list[tuple[float, float]]) -> dict[str, object]:
    return {
        "type": "way",
        "id": id,
        "tags": tags,
        "geometry": [{"lon": a, "lat": b} for a, b in pts],
    }


def sq(lon: float, lat: float, d: float = 0.0002) -> list[tuple[float, float]]:
    return [(lon, lat), (lon + d, lat), (lon + d, lat + d), (lon, lat + d), (lon, lat)]


SAMPLE = {
    "elements": [
        way(1, {"building": "yes", "height": "45"}, sq(139.7000, 35.6600)),
        way(
            2,
            {"building": "apartments", "building:levels": "4", "name": "Flat"},
            sq(139.7010, 35.6600),
        ),
        way(3, {"building": "house"}, sq(139.7020, 35.6600)),
        way(
            4, {"highway": "primary", "name": "Big Road"}, [(139.699, 35.6595), (139.703, 35.6595)]
        ),
        way(5, {"highway": "footway"}, [(139.699, 35.6596), (139.703, 35.6596)]),
        way(6, {"leisure": "park", "name": "Park"}, sq(139.7000, 35.6610, 0.0005)),
        {
            "type": "node",
            "id": 7,
            "lat": 35.6605,
            "lon": 139.7005,
            "tags": {"name": "Statue", "tourism": "artwork"},
        },
        {"type": "node", "id": 8, "lat": 35.6605, "lon": 139.7005, "tags": {"amenity": "bench"}},
    ]
}


def test_convert_and_roundtrip(tmp_path: Path) -> None:
    m = convert(SAMPLE, map_id="t", name="T", bbox=(35.659, 139.699, 35.662, 139.703))
    by = {f.id: f for f in m.features}
    assert set(by) == {"bldg_1", "bldg_2", "bldg_3", "road_4", "park_6", "lm_7"}
    assert (by["bldg_1"].height, by["bldg_2"].height, by["bldg_3"].height) == (45, 12, 6)
    assert by["bldg_2"].name == "Flat"
    x0, y0, x1, y1 = m.bounds
    assert x0 < 0 < x1 and y0 < 0 < y1
    text = dump_map(m)
    again = parse_map(text)
    assert again.features == m.features
    store = FileMapStore(tmp_path)
    store.save("t", text)
    assert store.list_ids() == ["t"]
    assert store.load("t").id == "t"
    disp = display_geojson(again)
    coords = disp["features"][0]["geometry"]["coordinates"][0][0]
    assert abs(coords[0] - 139.7) < 0.001 and abs(coords[1] - 35.66) < 0.001


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b.update(type="Nope"),
        lambda b: b.pop("smartkeeper"),
        lambda b: b["features"][0]["properties"].update(kind="castle"),
        lambda b: b["features"][0]["properties"].update(height=-1),
        lambda b: b["features"].append(b["features"][0]),
        lambda b: b["features"][0]["geometry"].update(coordinates=[[[0, 0], [1, 1], [0, 0]]]),
    ],
)
def test_invalid_maps_rejected(mutate: object) -> None:
    m = convert(SAMPLE, map_id="t", name="T")
    body = json.loads(dump_map(m))
    mutate(body)  # type: ignore[operator]
    with pytest.raises(ValidationFailed):
        parse_map(json.dumps(body))


def test_bad_map_id(tmp_path: Path) -> None:
    with pytest.raises(ValidationFailed):
        FileMapStore(tmp_path).load("../etc")
