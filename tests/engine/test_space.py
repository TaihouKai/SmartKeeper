"""engine 接入位置、感知、在场列表、移动与范围效果的校验。"""

from __future__ import annotations

from typing import Any

import pytest

from smartkeeper.contracts import (
    KP,
    Encounter,
    Movement,
    NotFound,
    PatchOp,
    Point,
    SpatialQuery,
    SweepShape,
    TargetRef,
    ValidationFailed,
)
from tests.engine.harness import Table, setup_table


def place(t: Table, moves: dict[str, tuple[float, float, float, str | None]]) -> None:
    """用管理员手动修改把实体放到指定位置。"""
    ops: list[PatchOp] = []
    for eid, (x, y, z, inside) in moves.items():
        ops.append(
            PatchOp(op="replace", path=f"/entities/{eid}/pos", value={"x": x, "y": y, "z": z})
        )
        ops.append(PatchOp(op="replace", path=f"/entities/{eid}/inside", value=inside))
    t.engine.admin_patch(t.game_id, ops)
    t.engine.refresh_handles(t.game_id)


def closed(t: Table) -> Table:
    t.declare_all()
    t.engine.close_round(t.game_id)
    return t


def codes(t: Table, **extra: Any) -> set[str]:
    with pytest.raises(ValidationFailed) as err:
        t.engine.apply_adjudication(t.game_id, t.simple_adjudication(**extra))
    return {p.code for p in err.value.problems} | {err.value.code}


def test_presence_lists_pc_and_npc_identical_fields() -> None:
    t = setup_table("single", 2)
    p0, p1 = t.players
    e0, e1 = t.entities(p0)[0], t.entities(p1)[0]
    place(t, {e0: (-50, 140, 0, None), e1: (-45, 140, 0, None)})  # NPC 在 (-50, 150)
    scene = t.engine.scene(t.game_id, p0)
    entries = scene.entities[0].presence
    assert len(entries) == 2
    dumps = [set(x.model_dump()) for x in entries]
    assert dumps[0] == dumps[1]
    # ref 不透露实体 id 或类型
    for x in entries:
        assert "npc" not in x.ref and "ent" not in x.ref
        assert x.label.startswith("#")
    # 排序只按代号
    assert [x.label for x in entries] == sorted(x.label for x in entries)


def test_multi_entities_have_independent_presence() -> None:
    t = setup_table("multi", 2)
    p0, p1 = t.players
    lead, comp = t.entities(p0)
    other = t.entities(p1)[0]
    rest = {e: (150.0, 150.0, 0.0, None) for e in t.entities(p1)[1:]}
    place(
        t,
        {lead: (-50, -60, 0, None), comp: (150, -60, 0, None), other: (145, -60, 0, None), **rest},
    )
    scene = t.engine.scene(t.game_id, p0)
    by_name = {x.name: x for x in scene.entities}
    lead_view = next(v for k, v in by_name.items() if "leader" in k)
    comp_view = next(v for k, v in by_name.items() if "companion" in k)
    assert len(comp_view.presence) == 1  # 只有身边的那个
    assert all(x.label != comp_view.presence[0].label for x in lead_view.presence)
    # 玩家的视图是两者的并集，自己的实体用角色名
    names = sorted(str(v.sheet["name"]) for v in t.engine.sheets(t.game_id, p0))
    assert sorted(x.name for x in scene.entities) == names


def test_handles_independent_and_renamable() -> None:
    t = setup_table("single", 2)
    p0, p1 = t.players
    e0, e1 = t.entities(p0)[0], t.entities(p1)[0]
    place(t, {e0: (-50, -60, 0, None), e1: (-45, -60, 0, None)})
    h01 = t.engine.scene(t.game_id, p0).entities[0].presence[0]
    h10 = t.engine.scene(t.game_id, p1).entities[0].presence[0]
    assert h01.ref != h10.ref
    t.engine.rename_handle(p0, h01.ref, label="The quiet one", note="suspicious")
    assert t.engine.scene(t.game_id, p0).entities[0].presence[0].label == "The quiet one"
    assert t.engine.scene(t.game_id, p1).entities[0].presence[0].label == h10.label
    assert t.engine.entity_for_ref(p0, h01.ref) == e1
    with pytest.raises(NotFound):
        t.engine.entity_for_ref(p1, h01.ref)  # 别人的 ref 用不了
    assert [s.label for s in t.engine.scene(t.game_id, p0).seen] == ["The quiet one"]


def test_unnamed_handles_listed_until_named() -> None:
    t = setup_table("single", 2)
    p0, p1 = t.players
    e0, e1 = t.entities(p0)[0], t.entities(p1)[0]
    place(t, {e0: (-50, -60, 0, None), e1: (-45, -60, 0, None)})
    assert (p0, e1) in t.engine.unnamed_handles(t.game_id)
    appearance, labels = t.engine.handle_context(t.game_id, p0, e1)
    assert appearance and isinstance(labels, list)
    t.engine.set_handle_label(p0, e1, "Grey coat")
    assert (p0, e1) not in t.engine.unnamed_handles(t.game_id)


def test_encounter_requires_perception() -> None:
    t = closed(setup_table("single", 2))
    p0, p1 = t.players
    # 两人隔着塔楼（0..20 × 0..20），互相看不见
    e0, e1 = t.entities(p0)[0], t.entities(p1)[0]
    place_closed(t, {e0: (-20, 10, 1.5, None), e1: (40, 10, 1.5, None)})
    enc = Encounter(players=(p0, p1), observed_by={p0: "sees", p1: "sees"})
    assert "adj.encounter_not_perceived" in codes(t, encounters=[enc])


def place_closed(t: Table, moves: dict[str, tuple[float, float, float, str | None]]) -> None:
    ops: list[PatchOp] = []
    for eid, (x, y, z, inside) in moves.items():
        ops.append(
            PatchOp(op="replace", path=f"/entities/{eid}/pos", value={"x": x, "y": y, "z": z})
        )
        ops.append(PatchOp(op="replace", path=f"/entities/{eid}/inside", value=inside))
    t.engine.admin_patch(t.game_id, ops)


def test_encounter_ok_when_visible_and_one_way() -> None:
    t = closed(setup_table("multi", 2))
    p0, p1 = t.players
    lead0, lead1 = t.entities(p0)[0], t.entities(p1)[0]
    far = {e: (190.0, 190.0, 0.0, None) for e in t.entities(p0)[1:]}
    far |= {e: (-90.0, 190.0, 0.0, None) for e in t.entities(p1)[1:]}
    # leader 的匿踪系数 0.5（agility 20），感知半径 70：相距 50 米时互相都感知不到
    place_closed(t, {lead0: (-50, -60, 0, None), lead1: (0, -60, 0, None), **far})
    one = Encounter(players=(p0, p1), observed_by={p0: "sees"})
    assert "adj.encounter_not_perceived" in codes(t, encounters=[one])
    place_closed(t, {lead1: (-20, -60, 0, None)})  # 30 米 <= 70 × 0.5
    t.engine.apply_adjudication(t.game_id, t.simple_adjudication(encounters=[one]))


def test_movement_distance_and_ability() -> None:
    t = setup_table("single", 2)
    t.declare_all(seconds=60)  # 本轮 60 秒
    t.engine.close_round(t.game_id)
    p0 = t.players[0]
    e0 = t.entities(p0)[0]
    decl = t.engine.declarations(t.game_id)
    from smartkeeper.contracts import Intent

    item = Intent.model_validate(decl[p0].payload["intent"]).items[0].id
    assert item is not None
    # move_speed = 60 + dex(60) = 120 m/min；从 (-50, -40) 出发
    far = Movement(entity=e0, to=Point(x=150, y=-40), because=item)
    assert "space.too_far" in codes(t, movements=[far])
    ok = Movement(entity=e0, to=Point(x=50, y=-40), because=item)
    t.engine.apply_adjudication(t.game_id, t.simple_adjudication(movements=[ok]))
    t.engine.rerun_round(t.game_id)
    teleport = Movement(entity=e0, to=Point(x=150, y=150), because=item, ability="first aid")
    t.engine.apply_adjudication(t.game_id, t.simple_adjudication(movements=[teleport]))
    t.engine.rerun_round(t.game_id)
    fake = Movement(entity=e0, to=Point(x=150, y=150), because=item, ability="teleport")
    assert "space.unknown_ability" in codes(t, movements=[fake])
    out = Movement(entity=e0, to=Point(x=900, y=0), because=item, ability="first aid")
    assert "space.out_of_bounds" in codes(t, movements=[out])
    wrong = Movement(entity=e0, to=Point(x=30, y=10), inside="bldg_tower", because=item)
    assert "space.not_inside" in codes(t, movements=[wrong])
    right = Movement(entity=e0, to=Point(x=10, y=10, z=6), inside="bldg_tower", because=item)
    t.engine.apply_adjudication(t.game_id, t.simple_adjudication(movements=[right]))


def test_area_effects_must_come_from_query() -> None:
    t = closed(setup_table("multi", 2))
    p0, p1 = t.players
    comp0 = t.entities(p0)[1]  # companion，带 "long beam"（box 100000 × 3 × 5）
    victim = t.entities(p1)[0]
    others = {e: (190.0, 190.0, 0.0, None) for e in t.entities(p0)[:1] + t.entities(p1)[1:]}
    place_closed(t, {comp0: (-80, 10, 2, None), victim: (100, 10, 2, None), **others})
    q = SpatialQuery(
        query_id="q1",
        kind="sweep",
        entity=comp0,
        ability="long beam",
        toward=TargetRef(kind="entity", id=victim),
    )
    res = t.engine.spatial_query(t.game_id, q)
    assert res.result is not None
    assert victim in res.result.entities
    assert {"bldg_tower", "bldg_low"} <= set(res.result.features)
    assert comp0 not in res.result.entities
    assert res.shape is not None and res.shape.length == 100000
    ev = [x for x in t.engine.view_for(t.game_id, KP) if x.type == "spatial_query"]
    assert ev[-1].visibility.kind == "kp_only"
    from smartkeeper.contracts import AreaEffect

    bad = AreaEffect(query_id="q1", affected=(victim, "npc_1"))
    assert "adj.not_in_query" in codes(t, area_effects=[bad])
    assert "adj.unknown_query" in codes(t, area_effects=[AreaEffect(query_id="q9", affected=())])
    good = AreaEffect(query_id="q1", affected=(victim, "bldg_tower"))
    destroy = PatchOp(
        op="add", path="/map_changes/-", value={"feature": "bldg_tower", "status": "destroyed"}
    )
    adj = t.simple_adjudication(area_effects=[good], state_patch=[destroy])
    t.engine.apply_adjudication(t.game_id, adj)
    for o in adj.outcomes:
        t.engine.set_feedback_draft(t.game_id, o.player_id, "boom")
    t.engine.publish_round(t.game_id)
    # 被毁的楼：p0 的 companion 在 100 米外（感知半径 200）能看到，p1 的 leader 也在附近
    s0 = t.engine.scene(t.game_id, p0)
    assert [c.feature for c in s0.map_changes] == ["bldg_tower"]
    assert s0.map_changes[0].known_by == ()  # 不透露谁知道


def test_ability_without_shape_uses_kp_dimensions() -> None:
    t = closed(setup_table("multi", 2))
    comp0 = t.entities(t.players[0])[1]
    victim = t.entities(t.players[1])[0]
    q = SpatialQuery(
        query_id="q2",
        kind="sweep",
        entity=comp0,
        ability="swift",
        toward=TargetRef(kind="entity", id=victim),
    )
    with pytest.raises(ValidationFailed):
        t.engine.spatial_query(t.game_id, q)
    q = q.model_copy(update={"shape": SweepShape(kind="sphere", radius=5)})
    res = t.engine.spatial_query(t.game_id, q)
    assert res.shape is not None and res.shape.radius == 5


def test_unknown_map_change_feature_rejected() -> None:
    t = closed(setup_table("single", 2))
    bad = PatchOp(op="add", path="/map_changes/-", value={"feature": "bldg_nowhere"})
    assert "state.unknown_feature" in codes(t, state_patch=[bad])


def test_memory_feature_must_exist() -> None:
    t = closed(setup_table("single", 2))
    assert "adj.memory_unknown_feature" in codes(
        t, memory_entries=[{"features": ["bldg_nowhere"], "text": "x"}]
    )


def test_state_slice_has_no_hidden_or_foreign_data() -> None:
    t = setup_table("single", 2)
    p0, p1 = t.players
    e0, e1 = t.entities(p0)[0], t.entities(p1)[0]
    place(t, {e0: (-50, -60, 0, None), e1: (-45, -60, 0, None)})
    sl = t.engine.state_slice(t.game_id, p0)
    text = str(sl)
    assert e1 not in text and "npc_1" not in text
    assert "notes" not in text  # 隐藏字段
    other_name = t.engine.sheets(t.game_id, p1)[0].sheet["name"]
    assert str(other_name) not in text


def test_mentions_resolve_to_handle_table() -> None:
    t = setup_table("single", 2)
    p0, p1 = t.players
    e0, e1 = t.entities(p0)[0], t.entities(p1)[0]
    place(t, {e0: (-50, -60, 0, None), e1: (-45, -60, 0, None)})
    ref = t.engine.scene(t.game_id, p0).entities[0].presence[0].ref
    t.engine.rename_handle(p0, ref, label="Blond man")
    text, targets = t.engine.resolve_mentions(
        t.game_id,
        p0,
        f"I slap @[whoever]({ref}), walk to @[the bakery](feature:bldg_tower)"
        " and then to @[a spot](point:10,20,0)",
    )
    # 人换成代号；地点保留确切的引用，KP 才对得上（远处的地物不在“附近的地物”里）
    assert text == (
        "I slap @Blond man, walk to @[the bakery](feature:bldg_tower)"
        " and then to @[a spot](point:10,20,0)"
    )
    assert [(x.kind, x.id) for x in targets] == [
        ("entity", e1),
        ("feature", "bldg_tower"),
        ("point", None),
    ]
    assert t.engine.ref_for_entity(p0, e1) == ref
    other_ref = t.engine.scene(t.game_id, p1).entities[0].presence[0].ref
    with pytest.raises(ValidationFailed):
        t.engine.resolve_mentions(t.game_id, p0, f"@[x]({other_ref})")
    with pytest.raises(ValidationFailed):
        t.engine.resolve_mentions(t.game_id, p0, "@[x](feature:bldg_nowhere)")


def test_cannot_target_unknown_entity() -> None:
    from smartkeeper.contracts import ActionItem, Intent

    t = setup_table("single", 2)
    p0 = t.players[0]
    e0 = t.entities(p0)[0]
    place(t, {e0: (150, 150, 0, None)})
    # npc_1 从没被 p0 感知过：没有代号，不能指代
    bad = Intent(
        items=(ActionItem(actor=e0, verb="greet", targets=(TargetRef(kind="entity", id="npc_1"),)),)
    )
    with pytest.raises(ValidationFailed):
        t.engine.declare_action(p0, "hi", bad)


def test_place_names_resolve_to_locations() -> None:
    from smartkeeper.contracts import Place

    t = setup_table("single", 2)
    loc = t.engine.resolve_place(t.game_id, Place(place="Tower", floor=3))
    assert loc.inside == "bldg_tower" and loc.pos.z == 6
    assert t.engine.resolve_place(t.game_id, Place(place="tower", roof=True)).pos.z == 30
    clock = t.engine.resolve_place(t.game_id, Place(place="Clock"))
    assert (clock.pos.x, clock.pos.y, clock.inside) == (25, 75, None)
    with pytest.raises(ValidationFailed):
        t.engine.resolve_place(t.game_id, Place(place="Nowhere"))
