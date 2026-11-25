"""结盟与友军：玩家互相同意才结成，任何一方可以解除；技能的 affects、脚本里的 ally、光环都按友军算。"""

from __future__ import annotations

from typing import Any, cast

import pytest
from pydantic import JsonValue

from smartkeeper.contracts import NotFound, PatchOp, RulePack, ShapeDef, ValidationFailed
from smartkeeper.rules import RulesService
from tests.engine.harness import Table, setup_table
from tests.engine.test_timeline import wait
from tests.fixtures import load_pack


def area_pack() -> RulePack:
    pack = load_pack("single")
    tpl = pack.templates[0]
    g = tpl.groups[0].model_copy(update={"shapes": ShapeDef(allowed=("sphere",))})
    return pack.model_copy(update={"templates": (tpl.model_copy(update={"groups": (g,)}),)})


def table() -> tuple[Table, list[str], list[str]]:
    t = setup_table("single", 3, pack=area_pack())
    ents = [t.entities(p)[0] for p in t.players]
    # 三个人站在一起（50 米内）
    t.engine.admin_patch(
        t.game_id,
        [
            PatchOp(op="replace", path=f"/entities/{e}/pos", value={"x": 10 * i, "y": 0, "z": 0})
            for i, e in enumerate(ents)
        ],
    )
    t.engine.refresh_handles(t.game_id)
    return t, t.players, ents


def ref(t: Table, viewer: str, entity: str) -> str:
    r = t.engine.ref_for_entity(viewer, entity)
    assert r is not None
    return r


def ally(t: Table, p0: str, p1: str, e1: str) -> None:
    view = t.engine.propose_alliance(t.game_id, p0, ref(t, p0, e1))
    assert len(view.outgoing) == 1
    incoming = t.engine.alliance_view(t.game_id, p1).incoming
    assert len(incoming) == 1
    t.engine.answer_alliance(t.game_id, p1, incoming[0].id, True)


def add_entries(t: Table, entity: str, rows: list[dict[str, Any]]) -> None:
    t.engine.admin_patch(
        t.game_id,
        [
            PatchOp(
                op="add",
                path=f"/entities/{entity}/sheet/groups/skills",
                value=cast(JsonValue, rows),
            )
        ],
    )


def begin(t: Table) -> None:
    for p in t.players:
        wait(t, p, 10)
    t.engine.close_round(t.game_id)
    t.engine.begin_plan(t.game_id)


def next_round(t: Table) -> None:
    for p in t.players:
        wait(t, p, 10)
    t.play_round()


def test_both_must_agree_and_either_can_end_it() -> None:
    t, (p0, p1, p2), (_e0, e1, e2) = table()
    e = t.engine
    ally(t, p0, p1, e1)
    assert len(e.alliance_view(t.game_id, p0).allies) == 1
    assert len(e.alliance_view(t.game_id, p1).allies) == 1
    assert not e.alliance_view(t.game_id, p2).allies
    with pytest.raises(ValidationFailed):
        e.propose_alliance(t.game_id, p0, ref(t, p0, e1))  # 已经结盟了
    # 互相提议直接结成
    e.propose_alliance(t.game_id, p2, ref(t, p2, e1))
    e.propose_alliance(t.game_id, p1, ref(t, p1, e2))
    assert len(e.alliance_view(t.game_id, p1).allies) == 2
    # 一方解除，双方都收到通知
    pact = e.alliance_view(t.game_id, p1).allies[0].id
    e.withdraw_alliance(t.game_id, p0, pact)
    assert len(e.alliance_view(t.game_id, p1).allies) == 1
    kinds = [x.payload["kind"] for x in e.view_for(t.game_id, p1) if x.type == "alliance_notice"]
    assert kinds[-1] == "broken"
    with pytest.raises(NotFound):
        e.withdraw_alliance(t.game_id, p2, pact)  # 不是自己的
    # 拒绝
    e.propose_alliance(t.game_id, p0, ref(t, p0, e2))
    prop = e.alliance_view(t.game_id, p2).incoming[0].id
    e.answer_alliance(t.game_id, p2, prop, False)
    assert not e.alliance_view(t.game_id, p0).outgoing


def test_affects_and_ally_follow_alliances() -> None:
    t, (p0, p1, _p2), (e0, e1, e2) = table()
    add_entries(
        t,
        e0,
        [
            {
                "name": "bless",
                "fields": {"level": 1},
                "config": 'affects = "allies"',
                "script": "target.add(hp, 0)",
            },
            {
                "name": "shout",
                "fields": {"level": 1},
                "config": 'target = "none"\nshape = sphere(radius=100)',
                "script": "if ally:\n    target.add(hp, 0)\nelse:\n    target.damage(1)",
            },
        ],
    )
    begin(t)
    e = t.engine
    with pytest.raises(ValidationFailed) as err:
        e.use_entry(t.game_id, e0, "bless", e1, {}, "x")  # 还没结盟
    assert err.value.code == "use.wrong_side"
    ally(t, p0, p1, e1)
    e.use_entry(t.game_id, e0, "bless", e1, {}, "x")
    with pytest.raises(ValidationFailed):
        e.use_entry(t.game_id, e0, "bless", e2, {}, "x")
    first = e.use_entry(t.game_id, e0, "shout", None, {}, "x")
    hits = [
        x
        for x in e.current_attempt(t.game_id, e.game(t.game_id).current_round)
        if x.type == "entry_used"
    ]
    sides = {
        x.payload["target"]: x.payload["ally"]
        for x in hits
        if x.seq == first.seq or x.payload.get("area_of") == first.seq
    }
    assert sides == {e1: True, e2: False}


def str_of(t: Table, entity: str) -> float:
    """修正之后的力量（被修正过的数值字段跟推导值一起列出来）。"""
    sheet = t.engine.world_state(t.game_id)["entities"][entity]["sheet"]  # type: ignore[index]
    rules = RulesService()
    pack = area_pack()
    hit = next((d for d in rules.derive(pack, "person", sheet) if d.name == "str"), None)
    if hit is not None:
        return hit.value
    full = cast(dict[str, Any], rules.full_sheet(pack, "person", sheet))
    return float(full["fields"]["str"])


def test_aura_follows_position_and_alliance() -> None:
    t, (p0, p1, _p2), (e0, e1, e2) = table()
    base = {x: str_of(t, x) for x in (e0, e1, e2)}
    add_entries(
        t,
        e0,
        [
            {
                "name": "lead",
                "fields": {"level": 1},
                "config": 'aura = sphere(radius=50)\naffects = "allies"',
                "effects": [
                    {"description": "str +2", "target": "str", "formula": "str + 2", "priority": 1}
                ],
            }
        ],
    )
    ally(t, p0, p1, e1)
    next_round(t)
    # 自己和盟友 +2（自己不会算两次），不是盟友的不加
    assert str_of(t, e0) == base[e0] + 2
    assert str_of(t, e1) == base[e1] + 2
    assert str_of(t, e2) == base[e2]
    # 盟友走出圈，下一轮就没了
    t.engine.admin_patch(
        t.game_id,
        [PatchOp(op="replace", path=f"/entities/{e1}/pos", value={"x": 190, "y": 190, "z": 0})],
    )
    next_round(t)
    assert str_of(t, e1) == base[e1]
    assert str_of(t, e0) == base[e0] + 2


def test_aura_bonus_is_worked_out_on_whoever_carries_it() -> None:
    """光环加成里的 self. 是带着加成的那个人（例如按他的模板、他的属性），this. 是光环主人这一条的列。"""
    t, (p0, p1, _p2), (e0, e1, _e2) = table()
    t.engine.admin_patch(
        t.game_id, [PatchOp(op="replace", path=f"/entities/{e1}/sheet/fields/per", value=7)]
    )
    base = {x: str_of(t, x) for x in (e0, e1)}
    per0 = t.engine.world_state(t.game_id)["entities"][e0]["sheet"]["fields"]["per"]  # type: ignore[index]
    add_entries(
        t,
        e0,
        [
            {
                "name": "lead",
                "fields": {"level": 3},
                "config": 'aura = sphere(radius=50)\naffects = "allies"',
                "effects": [
                    {
                        "description": "",
                        "target": "str",
                        "formula": "self.str + self.per + this.level",
                    }
                ],
            }
        ],
    )
    ally(t, p0, p1, e1)
    next_round(t)
    assert str_of(t, e1) == base[e1] + 7 + 3
    assert str_of(t, e0) == base[e0] + float(cast(float, per0)) + 3


def test_aura_written_as_bonus_code() -> None:
    """光环的加成用常驻加成的代码写：self.str += …，可以按模板分情况。"""
    t, (p0, p1, _p2), (e0, e1, e2) = table()
    base = {x: str_of(t, x) for x in (e0, e1, e2)}
    add_entries(
        t,
        e0,
        [
            {
                "name": "lead",
                "fields": {"level": 1},
                "config": 'aura = sphere(radius=50)\naffects = "allies"',
                "bonus": 'if self.template == "person":\n    self.str += 2  # 统率\nelse:\n    self.str += 1',
            }
        ],
    )
    ally(t, p0, p1, e1)
    next_round(t)
    assert str_of(t, e0) == base[e0] + 2
    assert str_of(t, e1) == base[e1] + 2
    assert str_of(t, e2) == base[e2]


def test_new_script_syntax_runs() -> None:
    """生效时：self.hp -= 1 直接扣；with minutes(…) 里改推导值是限时修正。"""
    t, _players, (e0, e1, _e2) = table()
    add_entries(
        t,
        e0,
        [
            {
                "name": "slow",
                "fields": {"level": 1},
                "config": "range = 1000",
                "script": "self.hp -= 1\nwith minutes(10):\n    target.move_speed *= 0.5",
            }
        ],
    )
    begin(t)
    e = t.engine
    u = e.use_entry(t.game_id, e0, "slow", e1, {}, "x")
    ops = [a["op"] for a in cast(list[dict[str, Any]], u.payload["actions"])]  # type: ignore[index]
    assert ops == ["subtract", "modify"]


def test_bonus_can_depend_on_the_time_of_day() -> None:
    """time 是游戏里的钟点（剧本 20:00 开始），14:00 这种写法是时刻；过了时间加成就没了。"""
    from smartkeeper.engine.space import peers_of

    t, _players, (e0, _e1, _e2) = table()
    add_entries(
        t,
        e0,
        [
            {
                "name": "night",
                "fields": {"level": 1},
                "bonus": "if time >= 19:00 or time < 6:00:\n    self.str += 5",
            }
        ],
    )
    next_round(t)
    rules = RulesService()

    def now() -> float:
        st = t.engine.world_state(t.game_id)
        sheet = st["entities"][e0]["sheet"]  # type: ignore[index]
        return next(
            d.value
            for d in rules.derive(area_pack(), "person", sheet, peers_of(st, e0))
            if d.name == "str"
        )

    st = t.engine.world_state(t.game_id)
    assert st["clock"] == 20 * 3600
    base = float(cast(float, st["entities"][e0]["sheet"]["fields"]["str"]))  # type: ignore[index]
    assert now() == base + 5  # 20:00 多
    t.engine.admin_patch(t.game_id, [PatchOp(op="replace", path="/game_seconds", value=12 * 3600)])
    assert now() == base  # 第二天 08:00


def test_other_allies_leaves_the_holder_out() -> None:
    """other_allies：光环只给除了自己以外的友军；单体技能不能对自己用。"""
    t, (p0, p1, _p2), (e0, e1, _e2) = table()
    base = {x: str_of(t, x) for x in (e0, e1)}
    add_entries(
        t,
        e0,
        [
            {
                "name": "lead",
                "fields": {"level": 1},
                "config": 'aura = sphere(radius=50)\naffects = "other_allies"',
                "bonus": "self.str += 2",
            },
            {
                "name": "bless",
                "fields": {"level": 1},
                "config": 'affects = "other_allies"',
                "script": "target.hp += 0",
            },
        ],
    )
    ally(t, p0, p1, e1)
    next_round(t)
    assert str_of(t, e0) == base[e0]
    assert str_of(t, e1) == base[e1] + 2
    begin(t)
    with pytest.raises(ValidationFailed):
        t.engine.use_entry(t.game_id, e0, "bless", e0, {}, "x")
    t.engine.use_entry(t.game_id, e0, "bless", e1, {}, "x")
