"""spatial 的单独测试：手写的小地图，不导入 eventlog、world、kp、web。"""

from __future__ import annotations

import pytest

from smartkeeper.contracts import Body, MapChange, Point, SweepShape
from smartkeeper.spatial import ShapelySpatial
from tests.fixtures.maps import small_map

S = ShapelySpatial()
M = small_map()


def body(
    id: str,
    x: float,
    y: float,
    z: float = 0,
    inside: str | None = None,
    r: float = 100,
    c: float = 1,
) -> Body:
    return Body(id=id, pos=Point(x=x, y=y, z=z), inside=inside, perception_radius=r, concealment=c)


def beam(z: float, radius: float = 1.5) -> SweepShape:
    # 水平光束从西向东穿过 tower（0..20, 0..20）
    return SweepShape(
        kind="capsule", a=Point(x=-50, y=10, z=z), b=Point(x=150, y=10, z=z), radius=radius
    )


def test_beam_hits_tall_building_at_10m() -> None:
    inside_low = body("in_9", 10, 10, 9, inside="bldg_tower")
    inside_high = body("in_20", 10, 10, 20, inside="bldg_tower")
    r = S.sweep(M, [], [inside_low, inside_high], beam(10))
    assert "bldg_tower" in r.features
    hit = next(h for h in r.buildings if h.feature == "bldg_tower")
    assert (hit.z_from, hit.z_to) == (8.5, 11.5)
    assert r.entities == ("in_9",)


def test_beam_band_against_low_house() -> None:
    r = S.sweep(M, [], [], beam(10))
    hit = next(h for h in r.buildings if h.feature == "bldg_low")
    assert (hit.z_from, hit.z_to) == (8.5, 10.0)


def test_beam_at_40m_misses() -> None:
    r = S.sweep(M, [], [], beam(40))
    assert "bldg_tower" not in r.features
    assert "bldg_float" in r.features  # 浮空连廊 20..40，光束 38.5..41.5 擦到顶部


def test_beam_under_floating_building() -> None:
    r = S.sweep(M, [], [], beam(5))
    assert "bldg_float" not in r.features


def test_box_and_sphere_and_cone() -> None:
    e_near = body("near", 30, 10, 0)
    e_far = body("far", 300, 10, 0)
    box = SweepShape(
        kind="box",
        origin=Point(x=-50, y=10, z=2),
        toward=Point(x=0, y=10, z=2),
        length=100000,
        width=3,
        height=5,
    )
    r = S.sweep(M, [], [e_near, e_far], box)
    assert set(r.features) >= {"bldg_tower", "bldg_low"}
    assert set(r.entities) == {"near", "far"}
    sph = SweepShape(kind="sphere", center=Point(x=30, y=10, z=0), radius=11)
    r = S.sweep(M, [], [e_near, e_far], sph)
    assert set(r.features) >= {"bldg_tower", "bldg_low"}
    assert r.entities == ("near",)
    cone = SweepShape(
        kind="cone",
        origin=Point(x=30, y=-30, z=1),
        toward=Point(x=30, y=100, z=1),
        length=40,
        angle=10,
    )
    r = S.sweep(M, [], [e_near, e_far], cone)
    assert r.entities == ("near",)


def test_ground_level_line_of_sight_is_blocked() -> None:
    assert not S.line_of_sight(M, [], Point(x=-20, y=10, z=0), Point(x=40, y=10, z=0)).visible


def test_line_of_sight_blocked_then_visible_from_roof() -> None:
    a = Point(x=-20, y=10, z=1.5)
    b = Point(x=40, y=10, z=1.5)
    los = S.line_of_sight(M, [], a, b)
    assert not los.visible and los.blockers == ("bldg_tower",)
    roof = Point(x=-20, y=10, z=31)
    assert S.line_of_sight(M, [], roof, Point(x=40, y=10, z=31)).visible
    # 双向
    assert not S.line_of_sight(M, [], b, a).visible


def test_perception_rules() -> None:
    obs = body("obs", -20, 10, 1.5, r=100)
    behind = body("behind", 40, 10, 1.5)
    open_ = body("open", -20, 60, 1.5)
    too_far = body("far", -20, 150, 1.5)
    seen = S.perceivable(M, [], obs, [obs, behind, open_, too_far])
    assert seen == ["open"]


def test_same_building_needs_no_line_of_sight() -> None:
    a = body("a", 2, 2, 0, inside="bldg_tower")
    b = body("b", 18, 18, 0, inside="bldg_tower")
    assert S.perceivable(M, [], a, [a, b]) == ["b"]
    c = body("c", 18, 18, 0)  # 坐标相同但不在楼内：要隔墙看，看不见
    assert S.perceivable(M, [], a, [a, c]) == []


def test_concealment_makes_perception_one_way() -> None:
    hunter = body("hunter", 0, -50, 0, r=100, c=0.4)
    prey = body("prey", 0, -100, 0, r=100, c=1.0)  # 距离 50
    assert S.perceivable(M, [], hunter, [hunter, prey]) == ["prey"]  # 50 <= 100 * 1.0
    assert S.perceivable(M, [], prey, [prey, hunter]) == []  # 50 > 100 * 0.4


def test_destroyed_building_stops_blocking_and_being_hit() -> None:
    a, b = Point(x=-20, y=10, z=1.5), Point(x=40, y=10, z=1.5)
    gone = [MapChange(feature="bldg_tower")]
    assert S.line_of_sight(M, gone, a, b).visible
    assert "bldg_tower" not in S.sweep(M, gone, [], beam(10)).features
    top_gone = [MapChange(feature="bldg_tower", above_z=5)]
    assert "bldg_tower" not in S.sweep(M, top_gone, [], beam(10)).features
    assert "bldg_tower" in S.sweep(M, top_gone, [], beam(3)).features
    assert not S.line_of_sight(M, top_gone, a, b).visible  # 下半截还在


def test_within_and_locate_and_bounds() -> None:
    r = S.within(M, [], [body("x", 25, 75)], Point(x=25, y=75, z=0), 5)
    assert "lm_clock" in r.features and "park_green" in r.features and r.entities == ("x",)
    assert S.locate(M, name="tower") == ["bldg_tower"]
    assert S.locate(M, name="Main Street") == ["road_main"]
    assert S.locate(M, point=Point(x=10, y=10)) == ["bldg_tower"]
    assert S.in_bounds(M, Point(x=0, y=0)) and not S.in_bounds(M, Point(x=500, y=0))
    assert S.inside_feature(M, "bldg_tower", Point(x=5, y=5))
    assert not S.inside_feature(M, "bldg_tower", Point(x=25, y=5))
    assert S.distance(Point(x=0, y=0, z=0), Point(x=3, y=4, z=12)) == 13


@pytest.mark.parametrize("kind", ["capsule", "box", "cone"])
def test_bad_shapes_rejected(kind: str) -> None:
    from smartkeeper.contracts import ValidationFailed

    with pytest.raises(ValidationFailed):
        S.sweep(M, [], [], SweepShape(kind=kind))  # type: ignore[arg-type]
