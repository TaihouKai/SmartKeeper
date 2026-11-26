"""目击记录：每轮开始按感知记；技能的 seen_within 按它判；转告复制原来的时间；locate 记下此刻。"""

from __future__ import annotations

from typing import Any, cast

import pytest

from smartkeeper.contracts import (
    GroupPreset,
    PatchOp,
    RulePack,
    TellIn,
    UseResult,
    ValidationFailed,
)
from smartkeeper.rules import RulesService
from tests.engine.harness import Table, setup_table
from tests.engine.test_timeline import publish
from tests.engine.test_uses import begin
from tests.fixtures import load_pack


def pack() -> RulePack:
    base = load_pack("single")
    tpl = base.templates[0]
    g = tpl.groups[0]
    presets = (
        GroupPreset(
            name="hex", fields={"level": 1}, config="seen_within = 60", script="target.damage(1)"
        ),
        GroupPreset(name="scry", fields={"level": 1}, script="target.locate()"),
    )
    tpl = tpl.model_copy(
        update={
            "groups": (g.model_copy(update={"presets": (*g.presets, *presets)}), *tpl.groups[1:])
        }
    )
    return base.model_copy(update={"templates": (tpl, *base.templates[1:])})


def table(n: int) -> tuple[Table, list[str]]:
    p = pack()
    assert RulesService().validate_pack(p) == []
    t = setup_table("single", n, pack=p)
    return t, [t.entities(x)[0] for x in t.players]


def state(t: Table) -> dict[str, Any]:
    return cast(dict[str, Any], t.engine.world_state(t.game_id))


def seen_at(t: Table, eid: str) -> dict[str, int]:
    return cast(dict[str, int], state(t)["entities"][eid].get("seen_at", {}))


def scatter(t: Table, ents: list[str]) -> None:
    """各自放到地图的角落，互相察觉不到。"""
    corners = [(-90, -90), (190, 190), (190, -90)]
    t.engine.admin_patch(
        t.game_id,
        [
            PatchOp(op="replace", path=f"/entities/{e}/pos", value={"x": x, "y": y, "z": 0})
            for e, (x, y) in zip(ents, corners, strict=False)
        ],
    )


def advance(t: Table, seconds: int) -> None:
    now = int(state(t)["game_seconds"])
    t.engine.admin_patch(
        t.game_id, [PatchOp(op="replace", path="/game_seconds", value=now + seconds)]
    )


def test_round_start_sightings_and_the_time_window() -> None:
    t, (a, b) = table(2)
    p0, p1 = t.players
    start = int(state(t)["game_seconds"])
    # 开局时两人挨着：互相记了一次
    assert seen_at(t, b)[p0] == start and seen_at(t, a)[p1] == start
    scatter(t, [a, b])
    advance(t, 30 * 60)
    begin(t)
    t.engine.use_entry(t.game_id, a, "hex", b, {}, "x")  # 30 分钟前见过：能用
    advance(t, 2 * 3600)
    with pytest.raises(ValidationFailed) as err:
        t.engine.use_entry(t.game_id, a, "hex", b, {}, "x")
    assert err.value.code == "use.not_seen_recently"


def test_locate_records_now() -> None:
    t, (a, b) = table(2)
    p0 = t.players[0]
    scatter(t, [a, b])
    advance(t, 5 * 3600)
    begin(t)
    u = t.engine.use_entry(t.game_id, a, "scry", b, {}, "x")
    publish(t, only=t.players, uses=[UseResult(seq=u.seq)])
    now = int(state(t)["game_seconds"])
    assert seen_at(t, b)[p0] == now
    begin(t)
    t.engine.use_entry(t.game_id, a, "hex", b, {}, "x")


def test_tell_copies_the_original_time_and_cannot_invent() -> None:
    t, (a, b, c) = table(3)
    p0, p1, p2 = t.players
    scatter(t, [a, b, c])
    advance(t, 3600)
    start = int(state(t)["game_seconds"])
    # 只有 p2 知道 b 在哪（十分钟前）；谁都不知道 c 在哪
    t.engine.admin_patch(
        t.game_id,
        [
            PatchOp(op="add", path=f"/entities/{b}/seen_at", value={p2: start - 600}),
            PatchOp(op="add", path=f"/entities/{c}/seen_at", value={}),
        ],
    )
    begin(t)
    publish(
        t,
        only=t.players,
        tells=[
            TellIn(source=p2, player=p0, about=b),  # p2 告诉 p0：复制 p2 的那次
            TellIn(source=p1, player=p0, about=c),  # p1 不知道 c 在哪：没有效果
        ],
    )
    assert seen_at(t, b)[p0] == start - 600
    assert p0 not in seen_at(t, c)


def test_bad_tells_are_rejected() -> None:
    t, _ = table(2)
    begin(t)
    adj = t.simple_adjudication(tells=[TellIn(source="nobody", player="p_x", about="e_x")])
    with pytest.raises(ValidationFailed) as err:
        t.engine.apply_adjudication(t.game_id, adj)
    codes = {p.code for p in err.value.problems}
    assert {
        "adj.tell_unknown_player",
        "adj.tell_unknown_source",
        "adj.tell_unknown_entity",
    } <= codes
