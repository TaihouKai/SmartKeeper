"""连续时间回合：移动耗时、回合在最早做完的行动处切开、没受影响的玩家不被通知，以及对话模式。"""

from __future__ import annotations

import pytest

from smartkeeper.contracts import (
    KP,
    ActionItem,
    Activity,
    IllegalState,
    Intent,
    Location,
    Movement,
    PatchOp,
    Point,
    Step,
    ValidationFailed,
)
from smartkeeper.engine.timeline import cut_time, location_at
from tests.engine.harness import Table, setup_table

# 夹具规则包 single：move_speed = 60 + dex(60) = 120 米/分钟，即 2 米/秒；开局在 (-50, -40) 和 (-48, -40)


def walk(t: Table, pid: str, to: Point, act: int = 0) -> None:
    ent = t.entities(pid)[0]
    item = ActionItem(actor=ent, verb="go", destination=Location(pos=to), act_seconds=act)
    t.engine.declare_action(pid, "go", Intent(items=(item,)))


def wait(t: Table, pid: str, seconds: int) -> None:
    ent = t.entities(pid)[0]
    t.engine.declare_action(
        pid, "wait", Intent(items=(ActionItem(actor=ent, verb="wait", act_seconds=seconds),))
    )


def publish(t: Table, only: list[str], **extra: object) -> None:
    e, g = t.engine, t.game_id
    adj = t.simple_adjudication(only=only, **extra)
    e.apply_adjudication(g, adj)
    for o in adj.outcomes:
        e.set_feedback_draft(g, o.player_id, "fb")
    e.publish_round(g)


def apart(t: Table) -> None:
    """把两个玩家放到地图的两个角上，互相感知不到，也远离 NPC（-50, 150）。"""
    e0, e1 = (t.entities(p)[0] for p in t.players)
    t.engine.admin_patch(
        t.game_id,
        [
            PatchOp(op="replace", path=f"/entities/{e0}/pos", value={"x": -90, "y": -90, "z": 0}),
            PatchOp(op="replace", path=f"/entities/{e1}/pos", value={"x": 190, "y": 190, "z": 0}),
        ],
    )


def pos(t: Table, eid: str) -> tuple[float, float, float]:
    p = t.engine.world_state(t.game_id)["entities"][eid]["pos"]  # type: ignore[index]
    return (p["x"], p["y"], p["z"])  # type: ignore[index]


def test_travel_time_walk_and_fly() -> None:
    t = setup_table("single", 2)
    e, g, p0 = t.engine, t.game_id, t.players[0]
    ent = t.entities(p0)[0]
    # 水平 100 米 + 竖直 20 米，走路按两条直角边：120 米 / 2 米每秒 = 60 秒
    secs, fly = e.travel_times(g, p0, Point(x=50, y=-40, z=0))[ent]
    assert (secs, fly) == (50, False)
    planned = e.plan_intent(
        g,
        Intent(
            items=(
                ActionItem(
                    actor=ent, verb="go", destination=Location(pos=Point(x=50, y=-40, z=20))
                ),
            )
        ),
    )
    assert planned.items[0].move_seconds == 60
    # 能飞：走斜边，fly_speed = 1 × move_speed
    e.admin_patch(
        g, [PatchOp(op="replace", path=f"/entities/{ent}/sheet/fields/can_fly", value=True)]
    )
    planned = e.plan_intent(
        g,
        Intent(
            items=(
                ActionItem(
                    actor=ent, verb="go", destination=Location(pos=Point(x=50, y=-40, z=20))
                ),
            )
        ),
    )
    assert planned.items[0].move_seconds == 51  # sqrt(100² + 20²) / 2 = 50.99


def test_location_at_walks_down_then_across() -> None:
    step = Step(
        item="a",
        start=Point(x=0, y=0, z=30),
        to=Location(pos=Point(x=40, y=0, z=0)),
        move=35,
        act=10,
    )
    act = Activity(player="p", start=100, end=145, steps=(step,))
    here = Location(pos=Point(x=0, y=0, z=30), inside="bldg")
    assert location_at(act, 100, here) == here
    mid_stairs = location_at(act, 110, here)
    assert mid_stairs is not None and mid_stairs.pos.x == 0 and mid_stairs.inside == "bldg"
    assert mid_stairs.pos.z == pytest.approx(30 - 70 * 10 / 35)
    on_street = location_at(act, 130, here)
    assert on_street is not None and on_street.pos.z == 0 and on_street.inside is None
    assert location_at(act, 140, here) == step.to
    assert cut_time({"e": act}, 100, 0) == 145
    assert cut_time({}, 100, 30) == 130


def test_round_ends_at_the_earliest_action_and_others_continue() -> None:
    t = setup_table("single", 2)
    e, g = t.engine, t.game_id
    p0, p1 = t.players
    e1 = t.entities(p1)[0]
    apart(t)
    wait(t, p0, 60)
    walk(t, p1, Point(x=190, y=-10))  # 200 米，100 秒
    e.close_round(g)
    assert e.round_window(g) == (0, 60)
    assert e.outcome_required(g) == [p0]
    publish(t, only=[p0])
    # 时间到 60 秒；p1 走到一半，没被通知，行动继续，他的时间还停在开场
    assert e.world_state(g)["game_seconds"] == 60
    assert pos(t, e1) == pytest.approx((190, 70, 0))
    assert e.player_seconds(g, p0) == 60 and e.player_seconds(g, p1) == 0
    assert e.required_players(g) == [p0]
    assert not [x for x in e.view_for(g, p1) if x.type == "feedback"]
    with pytest.raises(IllegalState):
        wait(t, p1, 5)  # 行动没做完的玩家不能反悔
    # 第二轮：p1 在 100 秒做完
    wait(t, p0, 300)
    e.close_round(g)
    assert e.round_window(g) == (60, 100)
    assert e.outcome_required(g) == [p1]
    publish(t, only=[p1])
    assert pos(t, e1) == pytest.approx((190, -10, 0))
    assert e.player_seconds(g, p1) == 100 and e.player_seconds(g, p0) == 60


def test_busy_player_sees_the_world_at_their_own_time() -> None:
    t = setup_table("single", 2)
    e, g = t.engine, t.game_id
    p0, p1 = t.players
    e0 = t.entities(p0)[0]
    wait(t, p0, 30)
    wait(t, p1, 600)
    e.close_round(g)
    publish(t, only=[p0])
    walk(t, p0, Point(x=-50, y=-10))  # p0 走开 30 米
    e.close_round(g)
    publish(t, only=[p0])
    # p1 的地图还停在开场：p0 在原地
    mine = e.scene(g, p1).entities[0]
    seen = {x.pos.y for x in mine.presence}
    assert -40.0 in seen
    assert pos(t, e0)[1] == pytest.approx(-10)


def test_affected_players_must_get_an_outcome() -> None:
    t = setup_table("single", 2)
    e, g = t.engine, t.game_id
    p0, p1 = t.players
    e1 = t.entities(p1)[0]
    wait(t, p0, 60)
    wait(t, p1, 600)
    e.close_round(g)
    # 改了忙着的玩家的角色卡：必须给他结果
    hurt = [PatchOp(op="replace", path=f"/entities/{e1}/sheet/fields/hp", value=3)]
    with pytest.raises(ValidationFailed) as err:
        e.apply_adjudication(g, t.simple_adjudication(only=[p0], state_patch=hurt))
    assert "adj.affected_needs_outcome" in {p.code for p in err.value.problems}
    # 移动了忙着的玩家的实体：也必须给他结果
    act = e.activities(g)[t.entities(p0)[0]]
    push = Movement(entity=e1, to=Point(x=-48, y=-30), because=act.steps[0].item)
    with pytest.raises(ValidationFailed) as err:
        e.apply_adjudication(g, t.simple_adjudication(only=[p0], movements=[push]))
    assert "adj.moved_needs_outcome" in {p.code for p in err.value.problems}
    # 给了结果：他的行动到此结束，要重新行动
    publish(t, only=[p0, p1], state_patch=hurt)
    assert e.activities(g) == {}
    assert sorted(e.required_players(g)) == sorted([p0, p1])


def test_presence_change_counts_as_affected() -> None:
    t = setup_table("single", 2)
    e, g = t.engine, t.game_id
    p0, p1 = t.players
    apart(t)
    wait(t, p1, 3000)
    walk(t, p0, Point(x=180, y=180))  # 走到 p1 身边
    e.close_round(g)
    with pytest.raises(ValidationFailed) as err:
        e.apply_adjudication(g, t.simple_adjudication(only=[p0]))
    assert "adj.affected_needs_outcome" in {p.code for p in err.value.problems}
    publish(t, only=[p0, p1])


def test_min_round_seconds() -> None:
    t = setup_table("single", 2)
    e, g = t.engine, t.game_id
    settings = e.game(g).settings.model_copy(update={"min_round_seconds": 90})
    e.update_settings(g, settings)
    wait(t, t.players[0], 5)
    wait(t, t.players[1], 600)
    e.close_round(g)
    assert e.round_window(g) == (0, 90)


# ---------------- 对话模式 ----------------


def test_talk_with_npc_blocks_the_round_until_it_ends() -> None:
    t = setup_table("single", 2)
    e, g = t.engine, t.game_id
    p0, p1 = t.players
    e0 = t.entities(p0)[0]
    # 把 p0 放到 NPC（-50, 150）身边
    e.admin_patch(
        g, [PatchOp(op="replace", path=f"/entities/{e0}/pos", value={"x": -50, "y": 145, "z": 0})]
    )
    talk = e.start_talk(p0, e0, "npc_1")
    assert talk.status == "active" and talk.b_player is None  # NPC 自动接受
    e.say(g, talk.id, p0, "hello")
    e.say(g, talk.id, KP, "evening")
    wait(t, p0, 10)
    wait(t, p1, 10)
    assert not e.ready_to_close(g)
    with pytest.raises(IllegalState):
        e.close_round(g)
    e.end_talk(g, talk.id, p0)
    assert e.ready_to_close(g)
    assert [m.text for m in e.talk(g, talk.id).messages] == ["hello", "evening"]
    # 对话的内容只有参与的玩家和 KP 看得到
    assert any(x.type == "talk_message" for x in e.view_for(g, p0))
    assert not any(x.type.startswith("talk_") for x in e.view_for(g, p1))


def test_accepting_a_talk_stops_the_partners_action() -> None:
    t = setup_table("single", 2)
    e, g = t.engine, t.game_id
    p0, p1 = t.players
    e0, e1 = t.entities(p0)[0], t.entities(p1)[0]
    wait(t, p0, 30)
    wait(t, p1, 600)
    e.close_round(g)
    publish(t, only=[p0])
    with pytest.raises(IllegalState):
        e.start_talk(p1, e1, e0)  # 行动还没做完的玩家不能发起
    talk = e.start_talk(p0, e0, e1)
    assert talk.status == "invited"
    declined = e.answer_talk(p1, talk.id, accept=False)
    assert declined.status == "declined" and e1 in e.activities(g)  # 拒绝：行动照常
    talk = e.start_talk(p0, e0, e1)
    e.answer_talk(p1, talk.id, accept=True)
    assert e1 not in e.activities(g)  # 接受：行动停止，对话后要重新行动
    assert p1 in e.required_players(g)
    e.say(g, talk.id, p1, "yes?")
    with pytest.raises(IllegalState):
        e.say(g, talk.id, KP, "not an npc")
    e.end_talk(g, talk.id, p1)


def test_talk_needs_perception() -> None:
    t = setup_table("single", 2)
    e = t.engine
    e0 = t.entities(t.players[0])[0]
    with pytest.raises(ValidationFailed):
        e.start_talk(t.players[0], e0, "npc_1")  # NPC 在 190 米外，感知不到


def test_bystanders_within_hearing_range_overhear() -> None:
    t = setup_table("single", 2)
    e, g = t.engine, t.game_id
    p0, p1 = t.players
    e0, e1 = t.entities(p0)[0], t.entities(p1)[0]
    # 夹具的 hear_distance = 30 × hear_multiplier(1)；NPC 在 (-50, 150)
    e.admin_patch(
        g,
        [
            PatchOp(op="replace", path=f"/entities/{e0}/pos", value={"x": -50, "y": 145, "z": 0}),
            PatchOp(op="replace", path=f"/entities/{e1}/pos", value={"x": -50, "y": 120, "z": 0}),
        ],
    )
    wait(t, p1, 600)  # p1 在 25 米外忙着自己的事
    talk = e.start_talk(p0, e0, "npc_1")
    e.say(g, talk.id, p0, "the bag is under the bench")
    e.end_talk(g, talk.id, p0)
    wait(t, p0, 10)
    e.close_round(g)
    assert e.overhearers(g) == {talk.id: [e1]}
    with pytest.raises(ValidationFailed) as err:
        e.apply_adjudication(g, t.simple_adjudication(only=[p0]))
    assert "adj.affected_needs_outcome" in {p.code for p in err.value.problems}
    publish(t, only=[p0, p1])


def test_empty_or_far_talks_are_not_overheard() -> None:
    t = setup_table("single", 2)
    e, g = t.engine, t.game_id
    p0, p1 = t.players
    e0, e1 = t.entities(p0)[0], t.entities(p1)[0]
    e.admin_patch(
        g,
        [
            PatchOp(op="replace", path=f"/entities/{e0}/pos", value={"x": -50, "y": 145, "z": 0}),
            PatchOp(op="replace", path=f"/entities/{e1}/pos", value={"x": -50, "y": 100, "z": 0}),
        ],
    )
    talk = e.start_talk(p0, e0, "npc_1")
    e.end_talk(g, talk.id, p0)  # 一句话都没说
    assert e.overhearers(g) == {}
    talk = e.start_talk(p0, e0, "npc_1")
    e.say(g, talk.id, p0, "psst")
    e.end_talk(g, talk.id, p0)
    assert e.overhearers(g) == {}  # 45 米，超出 30 米的听力范围
