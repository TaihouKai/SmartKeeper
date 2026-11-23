from __future__ import annotations

import pytest

from smartkeeper.contracts import (
    KP,
    ActionItem,
    Adjudication,
    IllegalState,
    Intent,
    Movement,
    PatchOp,
    Point,
    ValidationFailed,
)
from tests.engine.harness import Table, setup_table
from tests.fixtures import PACKS

SCALES = [2, 30]


@pytest.fixture(params=[(p, n) for p in PACKS for n in SCALES], ids=lambda x: f"{x[0]}-{x[1]}")
def table(request: pytest.FixtureRequest) -> Table:
    pack, n = request.param
    return setup_table(pack, n)


@pytest.fixture(params=PACKS)
def small(request: pytest.FixtureRequest) -> Table:
    return setup_table(request.param, 2)


def event_count(t: Table) -> int:
    return len(t.engine.view_for(t.game_id, KP))


# ---------------- 人数无关的完整流程 ----------------


def test_rounds_flow(table: Table) -> None:
    e = table.engine
    assert e.round(table.game_id).no == 1
    for _ in range(2):
        assert not e.ready_to_close(table.game_id)
        table.declare_all()
        assert e.ready_to_close(table.game_id)
        table.play_round()
    g = e.game(table.game_id)
    assert g.current_round == 3
    assert e.world_state(table.game_id)["game_seconds"] == 3600
    for pid in table.players:
        fb = [x for x in e.view_for(table.game_id, pid) if x.type == "feedback"]
        assert [x.payload["text"] for x in fb] == [f"feedback for {pid}"] * 2


def test_replay_is_deterministic(table: Table) -> None:
    e = table.engine
    for _ in range(2):
        table.declare_all()
        table.play_round()
    current = e.canonical(e.world_state(table.game_id))
    assert e.canonical(e.rebuild_state(table.game_id)) == current
    closed = {
        int(str(x.payload["round"])): x.seq
        for x in e.view_for(table.game_id, KP)
        if x.type == "round_closed"
    }
    for r in e.rounds(table.game_id):
        if r.status == "published":
            assert r.snapshot is not None
            rebuilt = e.rebuild_state(table.game_id, upto_seq=closed[r.no])
            assert e.canonical(rebuilt) == e.canonical(r.snapshot)


def test_player_views_are_isolated(table: Table) -> None:
    e = table.engine
    table.declare_all()
    table.play_round()
    for pid in table.players:
        for ev in e.view_for(table.game_id, pid):
            assert ev.visibility.kind == "public" or pid in ev.visibility.players


# ---------------- 状态机 ----------------


def test_illegal_transitions(small: Table) -> None:
    e, g = small.engine, small.game_id
    with pytest.raises(IllegalState):
        e.close_round(g)  # 没人提交
    small.declare_all()
    e.close_round(g)
    with pytest.raises(IllegalState):
        small.declare_all()  # 裁定中提交行动
    with pytest.raises(IllegalState):
        e.publish_round(g)  # 还没有草稿
    adj = small.simple_adjudication()
    e.apply_adjudication(g, adj)
    for o in adj.outcomes:
        e.set_feedback_draft(g, o.player_id, "x")
    e.publish_round(g)
    with pytest.raises(IllegalState):
        e.publish_round(g)  # 重复发布


def test_redeclare_overrides(small: Table) -> None:
    e, g = small.engine, small.game_id
    pid = small.players[0]
    ent = small.entities(pid)[0]
    e.declare_action(pid, "first", Intent(items=(ActionItem(actor=ent, verb="a"),)))
    e.declare_action(pid, "second", Intent(items=(ActionItem(actor=ent, verb="b"),)))
    assert e.declarations(g)[pid].payload["text"] == "second"


def test_chat_is_not_submission(small: Table) -> None:
    e, g = small.engine, small.game_id
    before = e.world_state(g)
    for pid in small.players:
        e.post_kp_chat(pid, "then I punch him")
    assert not e.ready_to_close(g)
    assert e.declarations(g) == {}
    assert e.world_state(g) == before
    small.declare_all(small.players[:-1])
    assert not e.ready_to_close(g)  # 差一个玩家


def test_declare_validation(small: Table) -> None:
    e = small.engine
    p0, p1 = small.players
    other = small.entities(p1)[0]
    with pytest.raises(ValidationFailed):
        e.declare_action(p0, "x", Intent(items=(ActionItem(actor=other, verb="a"),)))
    mine = small.entities(p0)[0]
    with pytest.raises(ValidationFailed):
        e.declare_action(
            p0, "x", Intent(items=(ActionItem(actor=mine, verb="a"),), unresolved=("him",))
        )
    secret = next(x for x in e.view_for(small.game_id, p1) if x.type == "pm_kp")
    with pytest.raises(ValidationFailed):
        e.declare_action(
            p0, "x", Intent(items=(ActionItem(actor=mine, verb="a"),), quotes=(secret.seq,))
        )


# ---------------- 裁定校验：任何一项不通过都不写入事件 ----------------


def rejected(t: Table, adj: Adjudication) -> set[str]:
    e, g = t.engine, t.game_id
    n = event_count(t)
    with pytest.raises(ValidationFailed) as err:
        e.apply_adjudication(g, adj)
    assert event_count(t) == n
    assert e.round(g).status == "adjudicating"
    return {p.code for p in err.value.problems} | {err.value.code}


def closed(t: Table) -> Table:
    t.declare_all()
    t.engine.close_round(t.game_id)
    return t


def test_missing_outcome_rejected(small: Table) -> None:
    t = closed(small)
    adj = t.simple_adjudication()
    adj = adj.model_copy(update={"outcomes": adj.outcomes[:-1]})
    assert "adj.outcome_count" in rejected(t, adj)


def test_duplicate_outcome_rejected(small: Table) -> None:
    t = closed(small)
    adj = t.simple_adjudication()
    adj = adj.model_copy(update={"outcomes": (*adj.outcomes, adj.outcomes[0])})
    assert "adj.outcome_count" in rejected(t, adj)


def first_field(t: Table, kind: str) -> tuple[str, str]:
    ent = t.entities(t.players[0])[0]
    tpl_name = str(t.engine.world_state(t.game_id)["entities"][ent]["template"])  # type: ignore[index]
    tpl = t.pack.template(tpl_name)
    assert tpl is not None
    fd = next(f for f in tpl.fields if f.kind == kind)
    return ent, fd.name


def test_patch_out_of_bounds_rejected(small: Table) -> None:
    t = closed(small)
    ent, res = first_field(t, "resource")
    adj = t.simple_adjudication(
        state_patch=[PatchOp(op="replace", path=f"/entities/{ent}/sheet/fields/{res}", value=-5)]
    )
    assert "sheet.below_min" in rejected(t, adj)


def test_patch_unknown_field_rejected(small: Table) -> None:
    t = closed(small)
    ent = t.entities(t.players[0])[0]
    adj = t.simple_adjudication(
        state_patch=[PatchOp(op="add", path=f"/entities/{ent}/sheet/fields/luck", value=3)]
    )
    assert "sheet.unknown_field" in rejected(t, adj)


def test_patch_derived_rejected(small: Table) -> None:
    t = closed(small)
    ent = t.entities(t.players[0])[0]
    adj = t.simple_adjudication(
        state_patch=[PatchOp(op="add", path=f"/entities/{ent}/sheet/fields/move_speed", value=999)]
    )
    assert "sheet.derived_not_writable" in rejected(t, adj)


def test_patch_cannot_touch_time_or_position(small: Table) -> None:
    t = closed(small)
    ent = t.entities(t.players[0])[0]
    adj = t.simple_adjudication(state_patch=[PatchOp(op="replace", path="/game_seconds", value=9)])
    assert "adj.patch_engine_only" in rejected(t, adj)
    adj = t.simple_adjudication(state_patch=[PatchOp(op="remove", path=f"/activities/{ent}")])
    assert "adj.patch_engine_only" in rejected(t, adj)
    adj = t.simple_adjudication(
        state_patch=[
            PatchOp(op="replace", path=f"/entities/{ent}/pos", value={"x": 1, "y": 1, "z": 1})
        ]
    )
    assert "adj.patch_position" in rejected(t, adj)


def test_unappliable_patch_rejected(small: Table) -> None:
    t = closed(small)
    adj = t.simple_adjudication(state_patch=[PatchOp(op="remove", path="/entities/nobody")])
    assert "patch.path_not_found" in rejected(t, adj)


def test_resolves_must_be_own_items(small: Table) -> None:
    t = closed(small)
    adj = t.simple_adjudication()
    o0, o1 = adj.outcomes
    swapped = (
        o0.model_copy(update={"resolves": o1.resolves}),
        o1.model_copy(update={"resolves": o0.resolves}),
    )
    assert "adj.resolves_foreign_item" in rejected(t, adj.model_copy(update={"outcomes": swapped}))
    bad = (o0.model_copy(update={"resolves": ("act_404",)}), o1)
    assert "adj.resolves_foreign_item" in rejected(t, adj.model_copy(update={"outcomes": bad}))


def test_movement_sources(small: Table) -> None:
    t = closed(small)
    p0, p1 = t.players
    e0, e1 = t.entities(p0)[0], t.entities(p1)[0]
    decl = t.engine.declarations(t.game_id)
    own0 = Intent.model_validate(decl[p0].payload["intent"]).items[0].id
    assert own0 is not None
    to = Point(x=1, y=1, z=0)

    def adj(*mvs: Movement) -> Adjudication:
        return t.simple_adjudication(movements=list(mvs))

    assert "adj.because_unknown_item" in rejected(
        t, adj(Movement(entity=e0, to=to, because="act_404"))
    )
    # p1 的实体借 p0 的条目自主移动：p0 的条目没有以它为目标
    assert "adj.because_foreign_item" in rejected(t, adj(Movement(entity=e1, to=to, because=own0)))
    # 玩家的实体不是 NPC
    assert "adj.because_not_npc" in rejected(
        t, adj(Movement(entity=e0, to=to, because=f"npc:{e1}"))
    )
    # 合法：自己的条目；由 NPC 引起
    t.engine.apply_adjudication(t.game_id, adj(Movement(entity=e0, to=to, because=own0)))
    t.engine.rerun_round(t.game_id)
    t.engine.apply_adjudication(t.game_id, adj(Movement(entity=e1, to=to, because="npc:npc_1")))


def test_pushed_by_other_player(small: Table) -> None:
    t = small
    p0, p1 = t.players
    e0, e1 = t.entities(p0)[0], t.entities(p1)[0]
    from smartkeeper.contracts import TargetRef

    t.engine.declare_action(
        p0,
        "push",
        Intent(
            items=(
                ActionItem(
                    actor=e0,
                    verb="push",
                    targets=(TargetRef(kind="entity", id=e1),),
                    act_seconds=60,
                ),
            )
        ),
    )
    t.declare_all([p1])
    t.engine.close_round(t.game_id)
    item = Intent.model_validate(t.engine.declarations(t.game_id)[p0].payload["intent"]).items[0].id
    assert item is not None
    adj = t.simple_adjudication(movements=[Movement(entity=e1, to=Point(x=2, y=0), because=item)])
    t.engine.apply_adjudication(t.game_id, adj)


def test_forced_close_unsubmitted_has_empty_resolves(small: Table) -> None:
    t = small
    p0, p1 = t.players
    t.declare_all([p0])
    t.engine.close_round(t.game_id, forced=True)
    adj = t.simple_adjudication()
    assert {o.player_id: o.resolves for o in adj.outcomes}[p1] == ()
    t.engine.apply_adjudication(t.game_id, adj)


def test_memory_entry_unknown_entity_rejected(small: Table) -> None:
    t = closed(small)
    adj = t.simple_adjudication(memory_entries=[{"entities": ["ghost"], "text": "x"}])
    assert "adj.memory_unknown_entity" in rejected(t, adj)


# ---------------- 重跑、手动修改、发布 ----------------


def test_rerun_discards_draft_without_events(small: Table) -> None:
    t = closed(small)
    e, g = t.engine, t.game_id
    n = event_count(t)
    e.apply_adjudication(g, t.simple_adjudication(kp_notes="first"))
    e.rerun_round(g)
    assert e.round(g).status == "adjudicating"
    assert event_count(t) == n
    t.engine.apply_adjudication(g, t.simple_adjudication(kp_notes="second"))
    for pid in t.players:
        e.set_feedback_draft(g, pid, "x")
    e.publish_round(g)
    assert e.world_state(g)["game_seconds"] == 1800
    assert e.world_state(g)["kp_notes"] == "second"
    assert len([x for x in e.view_for(g, KP) if x.type == "adjudication"]) == 1


def test_publish_requires_all_feedback(small: Table) -> None:
    t = closed(small)
    e, g = t.engine, t.game_id
    e.apply_adjudication(g, t.simple_adjudication(public_events=["boom"]))
    e.set_feedback_draft(g, t.players[0], "x")
    with pytest.raises(IllegalState):
        e.publish_round(g)
    e.set_feedback_draft(g, t.players[1], "y")
    with pytest.raises(IllegalState):
        e.publish_round(g)  # 有公共事件但没有广播稿
    e.set_broadcast_draft(g, "news")
    e.publish_round(g)
    pub = [x for x in e.view_for(g, "public") if x.type == "broadcast"]
    assert pub[-1].payload["text"] == "news"


def test_recover_restarts_adjudicating(small: Table) -> None:
    t = closed(small)
    assert t.engine.recover() == [t.game_id]


def test_game_over(small: Table) -> None:
    t = small
    t.declare_all()
    t.play_round(None)
    t.declare_all()
    t.engine.close_round(t.game_id)
    adj = t.simple_adjudication(game_over=True)
    t.engine.apply_adjudication(t.game_id, adj)
    for o in adj.outcomes:
        t.engine.set_feedback_draft(t.game_id, o.player_id, "the end")
    t.engine.publish_round(t.game_id)
    assert t.engine.game(t.game_id).status == "ended"


# ---------------- 骰子 ----------------


def test_rolls_are_logged(small: Table) -> None:
    t = closed(small)
    e, g = t.engine, t.game_id
    n = len([x for x in e.view_for(g, KP) if x.type == "dice_roll"])
    r = e.roll(g, "2d6+1", "test")
    assert 3 <= r.total <= 13
    ent = t.entities(t.players[0])[0]
    check = t.pack.checks[0].name
    res = e.run_check(g, ent, check, against=10)
    rolls = [x for x in e.view_for(g, KP) if x.type == "dice_roll"]
    assert len(rolls) == n + 2
    assert rolls[-1].payload["level"] == res.level
    assert rolls[-1].seq == res.roll.seq
    assert all(x.visibility.kind == "kp_only" for x in rolls)


def test_roll_only_while_adjudicating(small: Table) -> None:
    with pytest.raises(IllegalState):
        small.engine.roll(small.game_id, "1d6", "x")
