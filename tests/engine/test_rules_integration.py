from __future__ import annotations

import pytest

from smartkeeper.contracts import KP, PUBLIC, GameConfig, IllegalState, PatchOp, ValidationFailed
from tests.engine.harness import SCENARIO_PUBLIC, make_engine, setup_table, sheets_for
from tests.fixtures import PACKS, load_pack


def derived(t_engine: object, game_id: str, pid: str, name: str) -> float:
    from smartkeeper.engine import Engine

    assert isinstance(t_engine, Engine)
    view = t_engine.sheets(game_id, pid)[0]
    return next(d.value for d in view.derived if d.name == name)


@pytest.mark.parametrize("pack", PACKS)
def test_status_expiry_restores_derived(pack: str) -> None:
    t = setup_table(pack, 2)
    e, g, pid = t.engine, t.game_id, t.players[0]
    ent = t.entities(pid)[0]
    base = derived(e, g, pid, "perception_radius")
    t.declare_all()
    status = {
        "tag": "blessed",
        "expires_at": 2700,
        "modifier": {"target": "perception_radius", "op": "mul", "value": "2"},
    }
    adj = t.simple_adjudication(
        state_patch=[PatchOp(op="add", path=f"/entities/{ent}/sheet/statuses/-", value=status)],
    )
    t.play_round(adj)
    assert derived(e, g, pid, "perception_radius") == base * 2
    t.declare_all()
    t.play_round(t.simple_adjudication())  # 时间到 3600 秒，超过 2700
    assert derived(e, g, pid, "perception_radius") == base
    causes = [x.payload["cause"] for x in e.view_for(g, KP) if x.type == "state_patch"]
    assert "expiry" in causes


def test_sheet_history_points_to_feedback() -> None:
    t = setup_table("single", 2)
    e, g, pid = t.engine, t.game_id, t.players[0]
    ent = t.entities(pid)[0]
    t.declare_all()
    adj = t.simple_adjudication(
        state_patch=[PatchOp(op="replace", path=f"/entities/{ent}/sheet/fields/hp", value=3)]
    )
    t.play_round(adj)
    view = e.sheets(g, pid)[0]
    change = next(c for c in view.history if c.path == "fields.hp")
    assert (change.old, change.new, change.source_kind) == (11, 3, "feedback")
    fb = next(x for x in e.view_for(g, pid) if x.type == "feedback")
    assert change.source_seq == fb.seq
    # 隐藏字段不出现在玩家的角色卡里，也不出现在变更历史里
    assert "notes" not in view.sheet["fields"]  # type: ignore[operator]
    assert all("notes" not in c.path for c in view.history)
    # 别人的实体不在我的角色卡里
    assert [v.entity_id for v in e.sheets(g, pid)] == t.entities(pid)


def test_version_in_use_cannot_be_deleted_and_new_version_does_not_affect_game() -> None:
    t = setup_table("single", 2)
    e, g, pid = t.engine, t.game_id, t.players[0]
    before = derived(e, g, pid, "move_speed")
    with pytest.raises(IllegalState):
        e.delete_rulepack_version(t.pack_id, 1)
    pack = t.pack
    tpl = pack.templates[0]
    faster = tuple(
        d.model_copy(update={"formula": "600 + dex"}) if d.name == "move_speed" else d
        for d in tpl.derived
    )
    samples = tuple(
        s.model_copy(
            update={"expected": {k: v for k, v in s.expected.items() if k != "move_speed"}}
        )
        for s in pack.samples
    )
    v2 = pack.model_copy(
        update={"templates": (tpl.model_copy(update={"derived": faster}),), "samples": samples}
    )
    assert t.packs.save_version(t.pack_id, v2).version == 2
    assert derived(e, g, pid, "move_speed") == before
    e.delete_rulepack_version(t.pack_id, 2)  # 没被使用的版本可以删


def test_anonymous_broadcast_via_engine() -> None:
    t = setup_table("single", 2)
    e, g = t.engine, t.game_id
    e.post_broadcast(g, t.players[0], "who am I", anonymous=True)
    last = lambda aud: [x for x in e.view_for(g, aud) if x.type == "broadcast"][-1]  # noqa: E731
    assert last(t.players[1]).actor is None
    assert last(PUBLIC).actor is None
    assert last(KP).actor == t.players[0]


IDENTITIES = """---
start_time: "2030-01-01T20:00"
identities:
  mode: {mode}
  options:
    - {{id: a, name: Alpha}}
    - {{id: b, name: Beta}}
---
"""


@pytest.mark.parametrize("mode", ["draw", "choose"])
def test_identity(mode: str) -> None:
    e, packs = make_engine(seed=3)
    pack = load_pack("single")
    pid = packs.create_pack("x")
    packs.save_version(pid, pack)
    g = e.create_game(
        GameConfig(
            name="t",
            rulepack_id=pid,
            rulepack_version=1,
            scenario_public=IDENTITIES.format(mode=mode),
        )
    )
    p1, _ = e.add_player(g.id, "one")
    p2, _ = e.add_player(g.id, "two")
    p3, _ = e.add_player(g.id, "three")
    with pytest.raises(IllegalState):
        e.submit_character(p1.id, sheets_for(pack, 0))  # 先要有身份
    if mode == "draw":
        with pytest.raises(ValidationFailed):
            e.assign_identity(p1.id, "a")
        a = e.assign_identity(p1.id)
        b = e.assign_identity(p2.id)
        assert sorted([str(a.payload["identity"]), str(b.payload["identity"])]) == ["a", "b"]
        draws = [x for x in e.view_for(g.id, KP) if x.type == "dice_roll"]
        assert len(draws) == 2
    else:
        e.assign_identity(p1.id, "b")
        with pytest.raises(ValidationFailed):
            e.assign_identity(p2.id, "b")  # 已被占用
        e.assign_identity(p2.id, "a")
    with pytest.raises(IllegalState):
        e.assign_identity(p3.id, None if mode == "draw" else "a")  # 身份用完
    with pytest.raises(IllegalState):
        e.assign_identity(p1.id, None if mode == "draw" else "a")  # 已经有身份
    assert [x.type for x in e.view_for(g.id, p1.id)] == ["identity_assigned"]
    e.submit_character(p1.id, sheets_for(pack, 0))


def test_character_counts_enforced() -> None:
    e, packs = make_engine()
    pack = load_pack("multi")
    pid = packs.create_pack("x")
    packs.save_version(pid, pack)
    g = e.create_game(
        GameConfig(name="t", rulepack_id=pid, rulepack_version=1, scenario_public=SCENARIO_PUBLIC)
    )
    p, _ = e.add_player(g.id, "one")
    sheets = sheets_for(pack, 0)
    with pytest.raises(ValidationFailed):
        e.submit_character(p.id, sheets[:1])  # 缺随从
    with pytest.raises(ValidationFailed):
        e.submit_character(p.id, [*sheets, sheets[-1], sheets[-1]])  # 随从太多
    e.submit_character(p.id, [*sheets, sheets[-1]])  # 两个随从可以
    e.approve_character(p.id)
    assert len(e.controlled(g.id, p.id)) == 3


def test_token_is_hashed() -> None:
    e, packs = make_engine()
    pid = packs.create_pack("x")
    packs.save_version(pid, load_pack("single"))
    g = e.create_game(
        GameConfig(name="t", rulepack_id=pid, rulepack_version=1, scenario_public=SCENARIO_PUBLIC)
    )
    p, token = e.add_player(g.id, "one")
    found = e.player_by_token(token)
    assert found is not None and found.id == p.id
    assert e.player_by_token(token + "x") is None
    e.revoke_player(p.id)
    assert e.player_by_token(token) is None


def test_sheets_approved_once_pass_straight_away_in_a_new_game() -> None:
    """KP 审核通过过的一套卡（同一版规则书、同样的剧本公开部分和身份）在新开的局里原样再交就直接通过，
    带着当时的审核意见；卡改了一点、换了规则书版本，都要重新审。"""
    e, packs = make_engine(seed=3)
    pack = load_pack("single")
    pid = packs.create_pack("x")
    packs.save_version(pid, pack)

    def new_game(version: int = 1) -> str:
        g = e.create_game(
            GameConfig(
                name="t", rulepack_id=pid, rulepack_version=version, scenario_public=SCENARIO_PUBLIC
            )
        )
        return g.id

    first, _ = e.add_player(new_game(), "one")
    e.submit_character(first.id, sheets_for(pack, 0))
    assert e.character_review_needed(first.id)
    e.approve_character(first.id, "两张卡都通过了。")

    again, _ = e.add_player(new_game(), "one")
    e.submit_character(again.id, sheets_for(pack, 0))
    assert not e.character_review_needed(again.id)
    assert e.character_status(again.id) == "approved"
    ev = [x for x in e.view_for(again.game_id, again.id) if x.type == "character_approved"][-1]
    assert ev.payload["comments"] == "两张卡都通过了。" and ev.payload["reused"] is True
    assert len(e.controlled(again.game_id, again.id)) == len(sheets_for(pack, 0))

    changed, _ = e.add_player(new_game(), "two")
    e.submit_character(changed.id, sheets_for(pack, 1))
    assert e.character_review_needed(changed.id)

    packs.save_version(pid, pack)
    other_rules, _ = e.add_player(new_game(version=2), "three")
    e.submit_character(other_rules.id, sheets_for(pack, 0))
    assert e.character_review_needed(other_rules.id)


def test_approved_character_can_be_revised_before_the_game_starts() -> None:
    e, packs = make_engine(seed=3)
    pack = load_pack("single")
    pid = packs.create_pack("x")
    packs.save_version(pid, pack)
    g = e.create_game(
        GameConfig(name="t", rulepack_id=pid, rulepack_version=1, scenario_public=SCENARIO_PUBLIC)
    )
    p, _ = e.add_player(g.id, "one")
    e.submit_character(p.id, sheets_for(pack, 0))
    e.approve_character(p.id)
    assert e.character_status(p.id) == "approved"
    # 开局前：还能存草稿、重新提交，回到待审核
    e.save_character_draft(p.id, [])
    e.submit_character(p.id, sheets_for(pack, 1))
    assert e.character_status(p.id) == "submitted"
    first = e.controlled(g.id, p.id)
    e.scene(g.id, p.id)  # 建卡页看过一眼：旧角色有了代号
    assert {h.entity_id for h in e.handles(p.id)} == set(first)
    e.approve_character(p.id)
    # 重新通过：换掉上次的实体，不留下没人控制的旧角色
    state = e.world_state(g.id)
    ents = state["entities"]
    assert isinstance(ents, dict)
    now = e.controlled(g.id, p.id)
    assert len(now) == len(first) and set(ents) == set(now)
    # 新角色用新编号；旧角色的代号作废：不当成“见过的人”，也不拿去起外号
    assert not set(now) & set(first)
    assert {h.entity_id for h in e.handles(p.id)} <= set(now)
    assert e.unnamed_handles(g.id) == []
