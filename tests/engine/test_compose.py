"""界面上点出来的行动：不经过 KP 直接成为意图；一起走的一起到；用了技能的由引擎在结算时用掉；
不耗时、只对自己、没人看见的技能当场生效。"""

from __future__ import annotations

from typing import Any, cast

import pytest

from smartkeeper.contracts import (
    ActionItem,
    ComposedAction,
    Intent,
    Location,
    PatchOp,
    Point,
    TargetRef,
    ValidationFailed,
)
from tests.engine.test_timeline import apart
from tests.engine.test_uses import table


def test_moving_together_takes_the_slowest_and_arrives_together() -> None:
    t, a, b = table()
    e, g = t.engine, t.game_id
    # a 离目的地远、b 近；一起走时两人都按慢的那个算
    e.admin_patch(
        g,
        [
            PatchOp(op="replace", path=f"/entities/{a}/pos", value={"x": -90, "y": -90, "z": 0}),
            PatchOp(op="replace", path=f"/entities/{b}/pos", value={"x": 90, "y": 90, "z": 0}),
        ],
    )
    to = Location(pos=Point(x=100, y=100))
    alone = e.plan_intent(
        g,
        Intent(
            items=(
                ActionItem(actor=a, verb="", destination=to),
                ActionItem(actor=b, verb="", destination=to),
            )
        ),
    )
    slow, fast = (it.move_seconds for it in alone.items)
    assert slow > fast > 0
    together = e.plan_intent(
        g,
        Intent(
            items=(
                ActionItem(actor=a, verb="", destination=to, group="g0"),
                ActionItem(actor=b, verb="", destination=to, group="g0"),
            )
        ),
    )
    assert [it.move_seconds for it in together.items] == [slow, slow]


def test_composed_skills_take_their_cast_time_and_need_what_they_need() -> None:
    t, a, b = table()
    e, g = t.engine, t.game_id
    p0 = t.players[0]
    intent = e.compose_intent(
        g,
        p0,
        [
            ComposedAction(
                actor=a, entry="kit/zap", target=TargetRef(kind="entity", id=b), params={"mode": 1}
            )
        ],
    )
    (item,) = intent.items
    assert item.entry == "kit/zap" and item.params == {"mode": 1.0} and item.targets[0].id == b
    with pytest.raises(ValidationFailed) as err:
        e.compose_intent(g, p0, [ComposedAction(actor=a, entry="kit/zap")])
    assert err.value.code == "use.needs_target"
    with pytest.raises(ValidationFailed) as err:
        e.compose_intent(g, p0, [ComposedAction(actor=b, entry="burst")])
    assert err.value.code == "compose.not_yours"


def test_skills_in_actions_are_used_by_the_engine_once() -> None:
    t, a, _b = table()
    e, g = t.engine, t.game_id
    p0, p1 = t.players
    e.declare_action(p0, "fly", e.compose_intent(g, p0, [ComposedAction(actor=a, entry="fly")]))
    e.declare_action(
        p1, "wait", Intent(items=(ActionItem(actor=t.entities(p1)[0], verb="wait", act_seconds=5),))
    )
    e.close_round(g)
    e.begin_plan(g)
    assert e.auto_uses(g) == []
    e.auto_uses(g)  # 第二次不再用
    used = [u for u in e.planned_uses(g) if isinstance(u, dict) and u.get("entry") == "fly"]
    assert len(used) == 1 and cast(dict[str, Any], used[0])["item"]


def test_a_self_only_instant_skill_nobody_sees_takes_effect_at_once() -> None:
    t, a, _b = table()
    e, g = t.engine, t.game_id
    p0 = t.players[0]
    # 两人挨着：对方看得见，不能当场生效
    assert not e.instant_ok(g, p0, a, "fly")
    apart(t)
    assert e.instant_ok(g, p0, a, "fly")
    assert not e.instant_ok(g, p0, a, "burst")  # 有范围、不只对自己
    ev = e.instant_use(g, p0, a, "fly", {})
    assert ev is not None and ev.type == "instant_used"
    statuses = cast(dict[str, Any], e.world_state(g))["entities"][a]["sheet"]["statuses"]
    assert any(s.get("modifier", {}) and s["modifier"]["target"] == "can_fly" for s in statuses)


def test_moving_together_after_other_steps_arrives_at_the_same_moment() -> None:
    """a 先做 60 秒别的事再出发、b 一开始就能走：两人同一时刻到。"""
    t, a, b = table()
    e, g = t.engine, t.game_id
    to = Location(pos=Point(x=100, y=100))
    intent = e.plan_intent(
        g,
        Intent(
            items=(
                ActionItem(actor=a, verb="look", act_seconds=60),
                ActionItem(actor=a, verb="", destination=to, group="g0"),
                ActionItem(actor=b, verb="", destination=to, group="g0"),
            )
        ),
    )
    _, mine, theirs = intent.items
    assert 60 + mine.move_seconds == theirs.move_seconds


def test_a_quick_self_only_written_action_nobody_notices_gets_its_result_at_once() -> None:
    from smartkeeper.contracts import IllegalState

    t, a, b = table()
    e, g = t.engine, t.game_id
    p0 = t.players[0]
    quick = Intent(
        items=(ActionItem(actor=a, verb="glance at phone", act_seconds=2),), instant=True
    )
    assert not e.instant_ok_intent(g, p0, quick)  # 对方就在旁边，看得见
    apart(t)
    assert e.instant_ok_intent(g, p0, quick)
    assert not e.instant_ok_intent(g, p0, quick.model_copy(update={"instant": False}))
    slow = Intent(items=(ActionItem(actor=a, verb="search", act_seconds=60),), instant=True)
    assert not e.instant_ok_intent(g, p0, slow)
    on_them = Intent(
        items=(
            ActionItem(
                actor=a, verb="poke", act_seconds=1, targets=(TargetRef(kind="entity", id=b),)
            ),
        ),
        instant=True,
    )
    assert not e.instant_ok_intent(g, p0, on_them)
    tired = PatchOp(
        op="add",
        path=f"/entities/{a}/sheet/statuses/-",
        value={"tag": "tired", "source": "phone", "expires_at": None},
    )
    ev = e.apply_instant_result(g, p0, quick, "Nothing new.", [tired], "glance")
    assert ev.type == "instant_result" and ev.payload["text"] == "Nothing new."
    tags = [
        s["tag"] for s in cast(dict[str, Any], e.world_state(g))["entities"][a]["sheet"]["statuses"]
    ]
    assert "tired" in tags
    # 只能改自己的角色，不能改位置
    for bad in (
        tired.model_copy(update={"path": f"/entities/{b}/sheet/statuses/-"}),
        PatchOp(op="replace", path=f"/entities/{a}/pos", value={"x": 0, "y": 0, "z": 0}),
    ):
        with pytest.raises(ValidationFailed):
            e.apply_instant_result(g, p0, quick, "x", [bad])
    # 不能当场出的（例如要移动）拒绝
    with pytest.raises(IllegalState):
        e.apply_instant_result(g, p0, slow, "x", [])
