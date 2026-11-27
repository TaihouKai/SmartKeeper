"""连续时间回合：移动耗时、回合在最早做完的行动处切开、没受影响的玩家不被通知，以及对话模式。"""

from __future__ import annotations

from typing import Any, cast

import pytest

from smartkeeper.contracts import (
    KP,
    ActionItem,
    Activity,
    FieldDef,
    GroupPreset,
    IllegalState,
    Intent,
    Location,
    Movement,
    NotFound,
    PackParam,
    PatchOp,
    Point,
    RulePack,
    Step,
    ValidationFailed,
)
from smartkeeper.engine.timeline import cut_time, location_at
from tests.engine.harness import Table, setup_table
from tests.fixtures import load_pack

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


# ---------------- 掷骰公式字段 ----------------


def damage_pack() -> RulePack:
    """single 规则包的 skills 分组加一个掷骰公式字段 damage，和一个总是生效的固定条目 punch。"""
    pack = load_pack("single")
    tpl = pack.templates[0]
    g = tpl.groups[0]
    g = g.model_copy(
        update={
            "fields": (*g.fields, FieldDef(name="damage", kind="formula", required=False)),
            "presets": (
                GroupPreset.model_validate(
                    {"name": "punch", "fields": {"level": 2, "damage": "dice(this.level, 6) + 1"}}
                ),
            ),
        }
    )
    tpl = tpl.model_copy(update={"groups": (g, *tpl.groups[1:])})
    return pack.model_copy(update={"templates": (tpl, *pack.templates[1:])})


def test_roll_a_formula_field_of_a_fixed_entry() -> None:
    t = setup_table("single", 2, pack=damage_pack())
    e, g = t.engine, t.game_id
    e0 = t.entities(t.players[0])[0]
    wait(t, t.players[0], 5)
    wait(t, t.players[1], 5)
    e.close_round(g)
    res = e.roll_formula(g, e0, "damage", "punch", "punches the thief")
    assert len(res.rolls) == 2 and res.total == sum(res.rolls) + 1
    ev = next(x for x in e.view_for(g, KP) if x.type == "dice_roll")
    assert ev.payload["entry"] == "punch" and ev.payload["field"] == "damage"
    with pytest.raises(NotFound):
        e.roll_formula(g, e0, "damage", "kick", "no such skill")
    with pytest.raises(ValidationFailed):
        e.roll_formula(g, e0, "level", "punch", "not a formula")


def spend_pack() -> RulePack:
    """skills 分组：使用时填写的 cost（1..hp，从 hp 里扣），伤害 = (1d4 + 1) * floor(12 / this.cost)。"""
    pack = load_pack("single")
    tpl = pack.templates[0]
    g = tpl.groups[0]
    g = g.model_copy(
        update={
            "fields": (
                *g.fields,
                FieldDef(name="damage", kind="formula", required=False),
            ),
            "presets": (
                GroupPreset.model_validate(
                    {
                        "name": "bolt",
                        "fields": {"level": 1, "damage": "(1d4 + 1) * floor(12 / this.cost)"},
                    }
                ),
            ),
        }
    )
    tpl = tpl.model_copy(update={"groups": (g, *tpl.groups[1:])})
    return pack.model_copy(
        update={"templates": (tpl, *pack.templates[1:]), "params": (cost_param(g.name),)}
    )


def cost_param(group: str, low: str = "1") -> PackParam:
    """使用时选的 cost（low..hp，从 hp 里扣）。"""
    return PackParam(name="cost", min=low, max="hp", spends="hp", groups=(group,))


def test_param_spends_a_resource_once_per_attempt() -> None:
    t = setup_table("single", 2, pack=spend_pack())
    e, g = t.engine, t.game_id
    p0 = t.players[0]
    e0 = t.entities(p0)[0]
    hp = e.world_state(g)["entities"][e0]["sheet"]["fields"]["hp"]  # type: ignore[index]
    wait(t, p0, 5)
    wait(t, t.players[1], 5)
    e.close_round(g)
    e.begin_plan(g)
    low = e.roll_formula(g, e0, "damage", "bolt", "x")  # 没给 cost：按下限 1
    assert low.total == (sum(low.rolls) + 1) * 12
    with pytest.raises(ValidationFailed):
        e.roll_formula(g, e0, "damage", "bolt", "x", {"cost": 0})  # 小于下限
    with pytest.raises(ValidationFailed):
        e.roll_formula(g, e0, "damage", "bolt", "x", {"cost": 999})  # hp 不够
    e.roll_formula(g, e0, "damage", "bolt", "first attempt", {"cost": 3})
    # 重跑：之前那次的消耗作废，只算这一次
    e.begin_plan(g)
    res = e.roll_formula(g, e0, "damage", "bolt", "second attempt", {"cost": 4})
    assert res.total == (sum(res.rolls) + 1) * 3
    publish(t, only=t.players)
    assert e.world_state(g)["entities"][e0]["sheet"]["fields"]["hp"] == hp - 4  # type: ignore[index]


# ---------------- 设置物 ----------------


def trap_pack() -> RulePack:
    """skills 分组允许设置物；人人都有一个固定条目 trap：半径 5 米，感知系数 0.2，触发 1 次，通知设置者。"""
    pack = load_pack("single")
    tpl = pack.templates[0]
    g = tpl.groups[0]
    trap = {
        "name": "trap",
        "description": "a hidden snare",
        "fields": {"level": 1},
        "config": 'target = "none"\nplacement = placement(radius=5, perceive=0.2, charges=1)',
    }
    g = g.model_copy(update={"placements": True, "presets": (GroupPreset.model_validate(trap),)})
    tpl = tpl.model_copy(update={"groups": (g, *tpl.groups[1:])})
    return pack.model_copy(update={"templates": (tpl, *pack.templates[1:])})


def test_placed_trap_triggers_once_and_tells_its_owner() -> None:
    from smartkeeper.contracts import PlaceIn

    t = setup_table("single", 2, pack=trap_pack())
    e, g = t.engine, t.game_id
    p0, p1 = t.players
    e0, e1 = t.entities(p0)[0], t.entities(p1)[0]
    e.admin_patch(
        g,
        [
            PatchOp(op="replace", path=f"/entities/{e0}/pos", value={"x": -90, "y": -90, "z": 0}),
            PatchOp(op="replace", path=f"/entities/{e1}/pos", value={"x": 150, "y": 100, "z": 0}),
        ],
    )
    # 第一轮：p0 在 (100, 100) 设陷阱；p1 开始往西走 100 米（50 秒），这一轮只走到 (130, 100)
    wait(t, p0, 10)
    walk(t, p1, Point(x=50, y=100))
    e.close_round(g)
    item = e.activities(g)[e0].steps[0].item
    place = PlaceIn(owner=e0, entry="trap", at=Point(x=100, y=100), because=item)
    publish(t, only=[p0], placements=[place])
    traps = e.world_state(g)["placements"]
    assert isinstance(traps, dict) and list(traps) == ["pl_1_1"]
    assert traps["pl_1_1"]["radius"] == 5 and traps["pl_1_1"]["charges"] == 1  # type: ignore[index]
    # 设置者自己看得到；p1 在 30 米外，发现距离 90 × 0.2 = 18 米，看不到
    assert [x.mine for x in e.scene(g, p0).entities[0].placements] == [True]
    # 第二轮：p1 走过陷阱，被触发；设置者开了通知，也必须有结果
    wait(t, p0, 300)
    e.close_round(g)
    with pytest.raises(ValidationFailed) as err:
        e.apply_adjudication(g, t.simple_adjudication(only=[p1]))
    codes = {p.code for p in err.value.problems}
    assert "adj.triggered_needs_outcome" in codes
    assert e.placement_report(g)["triggered_this_round"] == {"pl_1_1": [e1]}
    publish(t, only=[p0, p1])
    assert e.world_state(g)["placements"] == {}  # 只能触发 1 次，用完移除


def test_placement_must_come_from_a_placement_entry() -> None:
    from smartkeeper.contracts import PlaceIn

    t = setup_table("single", 2, pack=trap_pack())
    e, g = t.engine, t.game_id
    p0 = t.players[0]
    e0 = t.entities(p0)[0]
    wait(t, p0, 10)
    wait(t, t.players[1], 10)
    e.close_round(g)
    item = e.activities(g)[e0].steps[0].item
    bad = PlaceIn(owner=e0, entry="first aid", at=Point(x=0, y=0), because=item)
    with pytest.raises(ValidationFailed) as err:
        e.apply_adjudication(
            g, t.simple_adjudication(placements=[bad], remove_placements=["pl_9_9"])
        )
    codes = {p.code for p in err.value.problems}
    assert {"adj.not_a_placement", "adj.unknown_placement"} <= codes


def test_triggering_reveals_an_invisible_trap() -> None:
    from smartkeeper.contracts import PlaceIn

    pack = trap_pack()
    tpl = pack.templates[0]
    g = tpl.groups[0]
    preset = g.presets[0]
    invisible = preset.model_copy(
        update={"config": 'target = "none"\nplacement = placement(radius=5, perceive=0)'}
    )
    g = g.model_copy(update={"presets": (invisible,)})
    pack = pack.model_copy(update={"templates": (tpl.model_copy(update={"groups": (g,)}),)})
    t = setup_table("single", 2, pack=pack)
    e, gid = t.engine, t.game_id
    p0, p1 = t.players
    e0, e1 = t.entities(p0)[0], t.entities(p1)[0]
    e.admin_patch(
        gid,
        [
            PatchOp(op="replace", path=f"/entities/{e0}/pos", value={"x": -90, "y": -90, "z": 0}),
            PatchOp(op="replace", path=f"/entities/{e1}/pos", value={"x": 150, "y": 100, "z": 0}),
        ],
    )
    wait(t, p0, 10)
    walk(t, p1, Point(x=50, y=100))
    e.close_round(gid)
    item = e.activities(gid)[e0].steps[0].item
    publish(
        t,
        only=[p0],
        placements=[PlaceIn(owner=e0, entry="trap", at=Point(x=100, y=100), because=item)],
    )
    wait(t, p0, 300)
    e.close_round(gid)
    publish(t, only=[p0, p1])
    # 无限次数：陷阱还在；感知系数 0，但 p1 触发过，所以知道它在那
    assert e.world_state(gid)["placements"]["pl_1_1"]["known_by"] == [e1]  # type: ignore[index]
    seen = e.scene(gid, p1).entities[0].placements
    assert len(seen) == 1 and not seen[0].mine


def test_placement_formulas_use_chosen_on_use_columns_and_spend() -> None:
    from smartkeeper.contracts import PlaceIn

    pack = trap_pack()
    tpl = pack.templates[0]
    g = tpl.groups[0]
    preset = g.presets[0]
    ward = preset.model_copy(
        update={
            "config": 'target = "none"\nplacement = placement(radius=this.cost * 2, perceive=0.2, charges=1)'
        }
    )
    g = g.model_copy(update={"presets": (ward,)})
    pack = pack.model_copy(
        update={
            "templates": (tpl.model_copy(update={"groups": (g,)}),),
            "params": (cost_param(g.name),),
        }
    )
    t = setup_table("single", 2, pack=pack)
    e, gid = t.engine, t.game_id
    p0 = t.players[0]
    e0 = t.entities(p0)[0]
    hp = e.world_state(gid)["entities"][e0]["sheet"]["fields"]["hp"]  # type: ignore[index]
    wait(t, p0, 10)
    wait(t, t.players[1], 10)
    e.close_round(gid)
    item = e.activities(gid)[e0].steps[0].item
    no_cost = PlaceIn(owner=e0, entry="trap", at=Point(x=0, y=0), because=item)
    too_much = no_cost.model_copy(update={"params": {"cost": 999}})
    with pytest.raises(ValidationFailed) as err:
        e.apply_adjudication(gid, t.simple_adjudication(placements=[too_much]))
    assert "roll.param_out_of_range" in {p.code for p in err.value.problems}
    place = no_cost.model_copy(update={"params": {"cost": 3}})
    publish(t, only=t.players, placements=[place])
    state = e.world_state(gid)
    assert state["placements"]["pl_1_1"]["radius"] == 6  # type: ignore[index]
    assert state["entities"][e0]["sheet"]["fields"]["hp"] == hp - 3  # type: ignore[index]


def test_runtime_fields_change_per_minute_without_notifying() -> None:
    pack = load_pack("single")
    tpl = pack.templates[0]
    fields = tuple(
        f.model_copy(update={"per_minute": "1"}) if f.name == "hp" else f for f in tpl.fields
    )
    pack = pack.model_copy(
        update={"templates": (tpl.model_copy(update={"fields": fields}), *pack.templates[1:])}
    )
    t = setup_table("single", 2, pack=pack)
    e, g = t.engine, t.game_id
    p0, p1 = t.players
    e0, e1 = t.entities(p0)[0], t.entities(p1)[0]
    hp_max = e.world_state(g)["entities"][e0]["sheet"]["fields"]["hp"]  # type: ignore[index]
    e.admin_patch(
        g,
        [
            PatchOp(op="replace", path=f"/entities/{e0}/sheet/fields/hp", value=3),
            PatchOp(op="replace", path=f"/entities/{e1}/sheet/fields/hp", value=hp_max),
        ],
    )
    wait(t, p0, 150)
    wait(t, p1, 3000)
    e.close_round(g)
    publish(t, only=[p0])  # p1 回了血（已满，不变）也不算受到影响
    ents = e.world_state(g)["entities"]
    assert ents[e0]["sheet"]["fields"]["hp"] == 5.5  # type: ignore[index]  # 2.5 分钟 × 1
    assert ents[e1]["sheet"]["fields"]["hp"] == hp_max  # type: ignore[index]  # 截断在上限


# ---------------- 作用效果和持续性效果 ----------------


def magic_pack() -> RulePack:
    """single 规则包加一个护盾（运行值，无上限）和四个带技能脚本的固定条目：
    bolt：对象受到 5 点伤害；ward：对象护盾 + level×4，持续 1 分钟；haste：对象移动速度 + 施法者的 str，持续半分钟；
    drain：对象受到 damage 列（level×3）的伤害，自己回 2 点生命。"""
    pack = load_pack("single")
    tpl = pack.templates[0]
    shield = FieldDef(name="shield", kind="resource", cls="runtime", min="0", initial="0")
    g = tpl.groups[0]
    presets = [
        {
            "name": "bolt",
            "id": "bolt",
            "fields": {"level": 1},
            "script": "target.damage(5)",
        },
        {
            "name": "ward",
            "fields": {"level": 2},
            "script": "target.add(shield, this.level * 4, 1)  # 一分钟",
        },
        {
            "name": "haste",
            "fields": {"level": 1},
            "script": "target.modify(move_speed, move_speed + str, 0.5)",
        },
        {
            "name": "drain",
            "fields": {"level": 2, "damage": "this.level * 3"},
            "script": "target.damage(this.damage); self.add(hp, 2)",
        },
        {
            "name": "echo",
            "fields": {"level": 1},
            "config": 'target = "none"',
            "script": 'if target.template == "person":\n    target.damage(9)\ntarget.damage(9)\nself.damage(1)',
        },
        {
            "name": "sort",
            "fields": {"level": 1},
            "script": (
                'if target.template == "nobody":\n'
                "    target.damage(100)\n"
                "elif target.template == self.template:\n"
                "    target.damage(3)\n"
                "    if 0:\n"
                "        target.damage(50)\n"
                "else:\n"
                "    self.damage(100)\n"
                "self.damage(1)"
            ),
        },
    ]
    damage = FieldDef(name="damage", kind="formula", required=False)
    g = g.model_copy(
        update={
            "fields": (*g.fields, damage),
            "presets": tuple(GroupPreset.model_validate(p) for p in presets),
        }
    )
    tpl = tpl.model_copy(update={"fields": (*tpl.fields, shield), "groups": (g, *tpl.groups[1:])})
    return pack.model_copy(update={"templates": (tpl, *pack.templates[1:])})


def fields_of(t: Table, eid: str) -> dict[str, object]:
    return t.engine.world_state(t.game_id)["entities"][eid]["sheet"]["fields"]  # type: ignore[index,return-value]


def test_damage_goes_through_shield_and_timed_shield_runs_out() -> None:
    from smartkeeper.contracts import UseResult

    t = setup_table("single", 2, pack=magic_pack())
    e, g = t.engine, t.game_id
    p0, p1 = t.players
    e0, e1 = t.entities(p0)[0], t.entities(p1)[0]
    hp = fields_of(t, e1)["hp"]
    wait(t, p0, 10)
    wait(t, p1, 10)
    e.close_round(g)
    e.begin_plan(g)
    ward = e.use_entry(g, e0, "ward", e1, {}, "shields p1")
    bolt1 = e.use_entry(g, e0, "bolt", e1, {}, "zap")
    bolt2 = e.use_entry(g, e0, "bolt", e1, {}, "zap again")
    # 声明了但裁定里没列出来：当作没发生（没写检定的技能必中，KP 写 hit=false 也不算）
    e.use_entry(g, e0, "bolt", e1, {}, "never happened")
    uses = [UseResult(seq=x.seq) for x in (ward, bolt1, bolt2)]
    publish(t, only=t.players, uses=uses)
    # 护盾 8：第一下 5 全吸收，第二下吸收 3、扣血 2；没列出的那一下不算
    assert fields_of(t, e1)["shield"] == 0
    assert fields_of(t, e1)["hp"] == hp - 2  # type: ignore[operator]
    # 再来一次：只加护盾，60 秒后到期，扣回剩下的
    wait(t, p0, 10)
    wait(t, p1, 10)
    e.close_round(g)
    e.begin_plan(g)
    again = e.use_entry(g, e0, "ward", e1, {}, "again")
    publish(t, only=t.players, uses=[UseResult(seq=again.seq)])
    assert fields_of(t, e1)["shield"] == 8
    wait(t, p0, 100)
    wait(t, p1, 100)
    e.close_round(g)
    publish(t, only=t.players)
    assert fields_of(t, e1)["shield"] == 0
    assert not e.world_state(g)["entities"][e1]["sheet"]["statuses"]  # type: ignore[index]


def test_timed_effect_freezes_the_users_values() -> None:
    from smartkeeper.contracts import UseResult

    t = setup_table("single", 2, pack=magic_pack())
    e, g = t.engine, t.game_id
    p0, p1 = t.players
    e0, e1 = t.entities(p0)[0], t.entities(p1)[0]
    wait(t, p0, 10)
    wait(t, p1, 10)
    e.close_round(g)
    e.begin_plan(g)
    source_str = fields_of(t, e0)["str"]
    before = e.derived_all(g)[e1]["move_speed"]
    haste = e.use_entry(g, e0, "haste", e1, {}, "speeds p1 up")
    publish(t, only=t.players, uses=[UseResult(seq=haste.seq)])
    statuses = e.world_state(g)["entities"][e1]["sheet"]["statuses"]  # type: ignore[index]
    assert isinstance(statuses, list) and len(statuses) == 1
    formula = statuses[0]["modifier"]["formula"]  # type: ignore[index]
    assert formula == f"move_speed + {source_str}"
    assert statuses[0]["expires_at"] == 10 + 30  # type: ignore[index]
    assert e.derived_all(g)[e1]["move_speed"] == before + source_str  # type: ignore[operator]


def test_script_hits_both_sides_and_can_target_yourself() -> None:
    from smartkeeper.contracts import UseResult

    t = setup_table("single", 2, pack=magic_pack())
    e, g = t.engine, t.game_id
    p0, p1 = t.players
    e0, e1 = t.entities(p0)[0], t.entities(p1)[0]
    hp0, hp1 = fields_of(t, e0)["hp"], fields_of(t, e1)["hp"]
    wait(t, p0, 10)
    wait(t, p1, 10)
    e.close_round(g)
    e.begin_plan(g)
    drain = e.use_entry(g, e0, "drain", e1, {}, "drains p1")
    assert [a["entity"] for a in drain.payload["actions"]] == [e1, e0]  # type: ignore[index,union-attr]
    publish(t, only=t.players, uses=[UseResult(seq=drain.seq)])
    assert fields_of(t, e1)["hp"] == hp1 - 6  # type: ignore[operator]  # this.damage = level × 3
    assert fields_of(t, e0)["hp"] == hp0  # type: ignore[comparison-overlap]  # 满血，加不上去
    wait(t, p0, 10)
    wait(t, p1, 10)
    e.close_round(g)
    e.begin_plan(g)
    own = e.use_entry(g, e0, "bolt", e0, {}, "zaps itself")
    # 要选对象的技能没给对象：引擎拒绝；设置成没有对象的技能只执行 self 的句子
    with pytest.raises(ValidationFailed) as err:
        e.use_entry(g, e0, "drain", None, {}, "no target")
    assert err.value.code == "use.needs_target"
    nobody = e.use_entry(g, e0, "echo", e1, {}, "target is ignored")
    assert nobody.payload["target"] is None
    assert [a["entity"] for a in nobody.payload["actions"]] == [e0]  # type: ignore[index,union-attr]
    publish(t, only=t.players, uses=[UseResult(seq=own.seq)])
    assert fields_of(t, e0)["hp"] == hp0 - 5  # type: ignore[operator]


def test_script_branches_pick_one_and_skip_target_questions_without_a_target() -> None:
    from smartkeeper.contracts import UseResult

    t = setup_table("single", 2, pack=magic_pack())
    e, g = t.engine, t.game_id
    p0, p1 = t.players
    e0, e1 = t.entities(p0)[0], t.entities(p1)[0]
    wait(t, p0, 10)
    wait(t, p1, 10)
    e.close_round(g)
    e.begin_plan(g)
    hit = e.use_entry(g, e0, "sort", e1, {}, "same template: elif branch")
    acts = [(a["entity"], a["amount"]) for a in hit.payload["actions"]]  # type: ignore[index,union-attr]
    assert acts == [(e1, 3), (e0, 1)]
    alone = e.use_entry(g, e0, "echo", None, {}, "no target: the whole if is skipped")
    acts = [(a["entity"], a["amount"]) for a in alone.payload["actions"]]  # type: ignore[index,union-attr]
    assert acts == [(e0, 1)]
    publish(t, only=t.players, uses=[UseResult(seq=hit.seq)])


def test_unknown_use_is_rejected() -> None:
    from smartkeeper.contracts import UseResult

    t = setup_table("single", 2, pack=magic_pack())
    e, g = t.engine, t.game_id
    wait(t, t.players[0], 10)
    wait(t, t.players[1], 10)
    e.close_round(g)
    with pytest.raises(ValidationFailed) as err:
        e.apply_adjudication(g, t.simple_adjudication(uses=[UseResult(seq=99999)]))
    assert "adj.unknown_use" in {p.code for p in err.value.problems}


# ---------------- 施放时间、冷却、致命字段 ----------------


def timing_pack() -> RulePack:
    """magic_pack 上加：hp 致命；技能分组有施放时间和冷却；nuke 1000 伤害冷却 1 分钟；ward 施放 2 分钟；bolt 0.5 分钟（瞬发）。"""
    pack = magic_pack()
    tpl = pack.templates[0]
    fields = tuple(
        x.model_copy(update={"vital": True}) if x.name == "hp" else x for x in tpl.fields
    )
    g = tpl.groups[0]
    presets = []
    for p in g.presets:
        if p.name == "ward":
            p = p.model_copy(update={"config": "cast_time = 2"})
        if p.name == "bolt":
            p = p.model_copy(update={"config": "cast_time = 0.5"})
        presets.append(p)
    nuke = GroupPreset.model_validate(
        {
            "name": "nuke",
            "fields": {"level": 1},
            "config": "cooldown = 1",
            "script": "target.damage(1000)",
        }
    )
    g = g.model_copy(update={"timing": True, "presets": (*presets, nuke)})
    tpl = tpl.model_copy(update={"fields": fields, "groups": (g, *tpl.groups[1:])})
    return pack.model_copy(update={"templates": (tpl, *pack.templates[1:])})


def test_cast_time_cooldown_and_death() -> None:
    from smartkeeper.contracts import UseResult

    t = setup_table("single", 2, pack=timing_pack())
    e, g = t.engine, t.game_id
    p0, p1 = t.players
    e0, e1 = t.entities(p0)[0], t.entities(p1)[0]
    assert e.cast_seconds(g, e0, "ward") == 120
    assert e.cast_seconds(g, e0, "bolt") == 0  # 不到 1 分钟算瞬发
    assert e.cast_seconds(g, e0, "nothing") == 0
    wait(t, p0, 10)
    wait(t, p1, 10)
    e.close_round(g)
    e.begin_plan(g)
    nuke = e.use_entry(g, e0, "nuke", e1, {}, "boom")
    publish(t, only=t.players, uses=[UseResult(seq=nuke.seq)])
    tags = {s["tag"] for s in e.world_state(g)["entities"][e1]["sheet"]["statuses"]}  # type: ignore[index,union-attr]
    assert "dead" in tags
    own = {s["tag"] for s in e.world_state(g)["entities"][e0]["sheet"]["statuses"]}  # type: ignore[index,union-attr]
    assert "cooldown:nuke" in own
    wait(t, p0, 10)
    wait(t, p1, 10)
    e.close_round(g)
    e.begin_plan(g)
    with pytest.raises(ValidationFailed) as err:
        e.use_entry(g, e0, "nuke", e1, {}, "again")
    assert err.value.code == "use.cooling_down"
    with pytest.raises(ValidationFailed) as err:
        e.use_entry(g, e1, "bolt", e0, {}, "the dead can't cast")
    assert err.value.code == "use.dead"
    publish(t, only=t.players)
    wait(t, p0, 60)
    wait(t, p1, 60)
    e.close_round(g)
    publish(t, only=t.players)
    own = {s["tag"] for s in e.world_state(g)["entities"][e0]["sheet"]["statuses"]}  # type: ignore[index,union-attr]
    assert "cooldown:nuke" not in own


# ---------------- 技能设置：对象、射程、要感知到对象、使用条件、动静 ----------------


def reach_pack() -> RulePack:
    """magic_pack 上加几个带技能设置的固定条目。"""
    pack = magic_pack()
    tpl = pack.templates[0]
    g = tpl.groups[0]
    extra = [
        {
            "name": "snipe",
            "fields": {"level": 1},
            "config": "range = 1",
            "script": "target.damage(1)",
        },
        {
            "name": "lance",
            "fields": {"level": 1},
            "config": "range = 2 + this.level",
            "script": "target.damage(1)",
        },
        {
            "name": "peek",
            "fields": {"level": 1},
            "config": "visible = True",
            "script": "target.damage(1)",
        },
        {
            "name": "focus",
            "fields": {"level": 1},
            "config": "requires = hp > 1000",
            "script": "self.add(hp, 1)",
        },
        {
            "name": "mend",
            "fields": {"level": 1},
            "config": 'target = "self"',
            "script": "target.damage(2)",
        },
        {
            "name": "boom",
            "fields": {"level": 1},
            "config": "noise = 3",
            "script": "target.damage(1)",
        },
    ]
    g = g.model_copy(
        update={"presets": (*g.presets, *(GroupPreset.model_validate(p) for p in extra))}
    )
    tpl = tpl.model_copy(update={"groups": (g, *tpl.groups[1:])})
    return pack.model_copy(update={"templates": (tpl, *pack.templates[1:])})


def test_skill_config_is_enforced_by_the_engine() -> None:
    t = setup_table("single", 3, pack=reach_pack())
    e, g = t.engine, t.game_id
    p0, p1, p2 = t.players
    e0, e1 = t.entities(p0)[0], t.entities(p1)[0]
    for p in t.players:
        wait(t, p, 10)
    e.close_round(g)
    e.begin_plan(g)

    def code(entry: str, target: str | None) -> str:
        with pytest.raises(ValidationFailed) as err:
            e.use_entry(g, e0, entry, target, {}, "x")
        return err.value.code

    # 实体相隔 2 米
    assert code("snipe", e1) == "use.out_of_range"
    assert e.use_entry(g, e0, "lance", e1, {}, "3 m reach").payload["target"] == e1
    assert code("focus", e1) == "use.requires"
    mend = e.use_entry(g, e0, "mend", e1, {}, "only on yourself")
    assert mend.payload["target"] == e0
    assert [a["entity"] for a in mend.payload["actions"]] == [e0]  # type: ignore[index,union-attr]
    # 动静 3 米：p1（2 米）察觉得到，p2（4 米）察觉不到
    boom = e.use_entry(g, e0, "boom", e1, {}, "noisy")
    assert boom.payload["heard_by"] == [p1]
    from smartkeeper.contracts import UseResult

    publish(t, only=t.players, uses=[UseResult(seq=boom.seq, hit=False)])
    noticed = [x for x in e.view_for(g, p1) if x.type == "entry_noticed"]
    assert len(noticed) == 1 and noticed[0].payload["entry"] == "boom"
    assert not [x for x in e.view_for(g, p2) if x.type == "entry_noticed"]

    # 对象要在感知里：把两人分开
    for p in t.players:
        wait(t, p, 10)
    e.close_round(g)
    e.admin_patch(
        g, [PatchOp(op="replace", path=f"/entities/{e1}/pos", value={"x": 190, "y": 190, "z": 0})]
    )
    e.begin_plan(g)
    assert code("peek", e1) == "use.not_perceived"


def test_placement_obeys_range_requirement_and_cooldown() -> None:
    from smartkeeper.contracts import PlaceIn

    pack = trap_pack()
    tpl = pack.templates[0]
    g0 = tpl.groups[0]
    near = g0.presets[0].model_copy(
        update={
            "config": 'target = "none"\nrange = 10\nvisible = True\nnoise = 20\ncooldown = 1\n'
            "placement = placement(radius=5)"
        }
    )
    pack = pack.model_copy(
        update={
            "templates": (
                tpl.model_copy(update={"groups": (g0.model_copy(update={"presets": (near,)}),)}),
            )
        }
    )
    t = setup_table("single", 2, pack=pack)
    e, g = t.engine, t.game_id
    p0, p1 = t.players
    e0, e1 = t.entities(p0)[0], t.entities(p1)[0]
    e.admin_patch(
        g,
        [
            PatchOp(op="replace", path=f"/entities/{e0}/pos", value={"x": -90, "y": -90, "z": 0}),
            PatchOp(op="replace", path=f"/entities/{e1}/pos", value={"x": -75, "y": -90, "z": 0}),
        ],
    )
    wait(t, p0, 10)
    wait(t, p1, 10)
    e.close_round(g)
    item = e.activities(g)[e0].steps[0].item
    far = PlaceIn(owner=e0, entry="trap", at=Point(x=100, y=100), because=item)
    with pytest.raises(ValidationFailed) as err:
        e.apply_adjudication(g, t.simple_adjudication(placements=[far]))
    assert "use.out_of_range" in {p.code for p in err.value.problems}
    ok = PlaceIn(owner=e0, entry="trap", at=Point(x=-85, y=-90), because=item)
    publish(t, only=t.players, placements=[ok])
    statuses = e.world_state(g)["entities"][e0]["sheet"]["statuses"]  # type: ignore[index]
    assert "cooldown:trap" in {s["tag"] for s in statuses}  # type: ignore[index,union-attr]
    # 动静 20 米：15 米外的 p1 察觉到有人放了 trap
    noticed = [x for x in e.view_for(g, p1) if x.type == "entry_noticed"]
    assert [x.payload["entry"] for x in noticed] == ["trap"]


def test_cast_time_may_use_chosen_on_use_columns() -> None:
    pack = trap_pack()
    tpl = pack.templates[0]
    g0 = tpl.groups[0]
    slow = g0.presets[0].model_copy(
        update={
            "config": 'target = "none"\ncast_time = this.cost * 3\nplacement = placement(radius=5)'
        }
    )
    g0 = g0.model_copy(update={"presets": (slow,)})
    pack = pack.model_copy(
        update={
            "templates": (tpl.model_copy(update={"groups": (g0,)}),),
            "params": (cost_param(g0.name, "2"),),
        }
    )
    t = setup_table("single", 2, pack=pack)
    e0 = t.entities(t.players[0])[0]
    # 解析行动时还不知道这次填多少：按下限 2 算，6 分钟
    assert t.engine.cast_seconds(t.game_id, e0, "trap") == 360


def test_reactions_are_chosen_by_the_target() -> None:
    from smartkeeper.contracts import CheckDef, ReactionChoice, UseResult

    pack = magic_pack()
    checks = (
        CheckDef(name="zap", config="dice = 1d6\nsuccess = roll > difficulty"),
        CheckDef(name="wall", config="dice = 1000\nsuccess = True"),
        CheckDef(name="limp", config="dice = 0\nsuccess = True"),
    )
    tpl = pack.templates[0]
    g0 = tpl.groups[0]
    extra = [
        {
            "name": "blast",
            "fields": {"level": 1},
            "config": 'check = "zap"\nreactions = ["limp", "wall", "parry", "slowward"]',
            "script": "target.damage(5)",
        },
        {
            "name": "jab",
            "fields": {"level": 1},
            "config": 'check = "zap"\nreactions = ["limp"]',
            "script": "target.damage(2 if level >= 2 else 3)",
        },
        {
            "name": "aimed",
            "fields": {"level": 1},
            "config": 'check = "zap"\ndifficulty = 100',
            "script": "target.damage(5)",
        },
        {
            "name": "sure",
            "fields": {"level": 1},
            "config": "check = True",
            "script": "target.damage(1)",
        },
        # 当反应时让这次攻击无效，并给自己加 1 点护盾
        {
            "name": "parry",
            "fields": {"level": 1},
            "config": 'target = "self"',
            "script": "if reacting:\n    self.negate()\nself.add(shield, 1, 1)",
        },
        {
            "name": "slowward",
            "fields": {"level": 1},
            "config": 'target = "self"\ncast_time = 5',
            "script": "self.negate()",
        },
    ]
    g0 = g0.model_copy(
        update={
            "timing": True,
            "presets": (*g0.presets, *(GroupPreset.model_validate(p) for p in extra)),
        }
    )
    pack = pack.model_copy(
        update={
            "checks": (*pack.checks, *checks),
            "templates": (
                tpl.model_copy(update={"groups": (g0, *tpl.groups[1:])}),
                *pack.templates[1:],
            ),
        }
    )
    t = setup_table("single", 2, pack=pack)
    e, g = t.engine, t.game_id
    p0, p1 = t.players
    e0, e1 = t.entities(p0)[0], t.entities(p1)[0]
    hp = fields_of(t, e1)["hp"]
    wait(t, p0, 10)
    wait(t, p1, 10)
    e.close_round(g)
    e.begin_plan(g)
    # 不掷骰的必中；没有对抗、难度 100 的打不中
    assert e.use_entry(g, e0, "sure", e1, {}, "x").payload["hit"] is True
    assert e.use_entry(g, e0, "aimed", e1, {}, "x").payload["hit"] is False
    # 对象是玩家、技能可以被应对：先不判，等 p1 选
    blast = e.use_entry(g, e0, "blast", e1, {}, "x")
    jab = e.use_entry(g, e0, "jab", e1, {}, "x")
    assert blast.payload["hit"] is None and blast.payload["waiting_for"] == p1
    assert {x.seq for x in e.pending_reactions(g)} == {blast.seq, jab.seq}
    prompts = {x.seq: x for x in e.reaction_prompts(g, p1)}
    assert prompts[blast.seq].checks == ("limp", "wall")
    skills = {s.entry for s in prompts[blast.seq].skills}
    assert "parry" in skills and "slowward" not in skills  # 有施放时间的不能当反应
    assert e.reaction_prompts(g, p0) == []
    # 还没应对完，KP 不能裁定这次使用
    with pytest.raises(ValidationFailed) as err:
        e.apply_adjudication(g, t.simple_adjudication(uses=[UseResult(seq=blast.seq)]))
    assert "adj.reaction_pending" in {p.code for p in err.value.problems}
    # 要一次交齐
    with pytest.raises(ValidationFailed):
        e.react(g, p1, [ReactionChoice(seq=blast.seq, kind="check", check="wall")])
    with pytest.raises(ValidationFailed):
        e.react(
            g,
            p1,
            [
                ReactionChoice(seq=blast.seq, kind="check", check="nope"),
                ReactionChoice(seq=jab.seq),
            ],
        )
    # blast 用技能 parry 挡掉；jab 不抵抗（攻击方按难度 0 判，1d6 > 0 打中）
    e.react(
        g,
        p1,
        [
            ReactionChoice(seq=blast.seq, kind="skill", entry="parry"),
            ReactionChoice(seq=jab.seq, kind="none"),
        ],
    )
    assert e.pending_reactions(g) == []
    planned: dict[object, Any] = {cast(dict[str, Any], x)["seq"]: x for x in e.planned_uses(g)}
    assert planned[blast.seq]["hit"] is False and planned[blast.seq]["reaction"]["negated"] is True
    assert planned[jab.seq]["hit"] is True
    publish(t, only=t.players, uses=[UseResult(seq=blast.seq), UseResult(seq=jab.seq)])
    # blast 被挡、parry 给 p1 加了 1 点护盾，jab 打中 3：护盾吸收 1，扣血 2
    assert fields_of(t, e1)["hp"] == hp - 2  # type: ignore[operator]
    statuses = cast(
        list[dict[str, Any]], cast(Any, e.world_state(g))["entities"][e1]["sheet"]["statuses"]
    )
    assert not any(s["tag"] == "cooldown:parry" for s in statuses)  # parry 没有冷却


def test_travel_left_is_worked_out_by_the_engine() -> None:
    """本轮结束时还在路上的：离目的地还剩多少米、多少秒由引擎算好给 KP，不让 KP 自己估。"""
    from smartkeeper.contracts import Activity, Location, Point, Step
    from smartkeeper.engine import timeline

    walk = Step(
        item="i1", start=Point(x=0, y=0, z=0), to=Location(pos=Point(x=300, y=400, z=0)), move=100
    )
    act = Activity(player="p", start=0, end=100, steps=(walk,))
    meters, secs = timeline.travel_left(act, 40) or (0.0, 0)
    assert round(meters) == 300 and secs == 60
    assert timeline.travel_left(act, 100) is None


def test_noticing_something_tells_the_player_without_stopping_the_action() -> None:
    """只是察觉到了什么（有人走进感知范围）：收到结果，但行动照常继续；下一轮可以改主意，不改就不用提交。"""
    t = setup_table("single", 2)
    e, g = t.engine, t.game_id
    p0, p1 = t.players
    e1 = t.entities(p1)[0]
    apart(t)
    wait(t, p1, 3000)
    walk(t, p0, Point(x=180, y=180))  # 走到 p1 身边
    e.close_round(g)
    publish(t, only=[p0, p1])
    assert [x for x in e.view_for(g, p1) if x.type == "feedback"]
    assert e1 in e.activities(g)  # 行动还在
    assert e.required_players(g) == [p0]  # 回合不等他
    assert e.may_change(g, p1)
    # 他改主意：新的安排替换掉还没做完的行动
    wait(t, p1, 20)
    wait(t, p0, 60)
    e.close_round(g)
    assert e.activities(g)[e1].end - e.activities(g)[e1].start == 20


def test_interrupt_or_being_targeted_stops_the_action() -> None:
    """KP 说他得停下来应对（interrupt），行动到此结束。"""
    t = setup_table("single", 2)
    e, g = t.engine, t.game_id
    p0, p1 = t.players
    e1 = t.entities(p1)[0]
    apart(t)
    wait(t, p1, 3000)
    walk(t, p0, Point(x=180, y=180))
    e.close_round(g)
    adj = t.simple_adjudication(only=[p0, p1])
    adj = adj.model_copy(
        update={
            "outcomes": tuple(
                o.model_copy(update={"interrupt": o.player_id == p1}) for o in adj.outcomes
            )
        }
    )
    e.apply_adjudication(g, adj)
    for o in adj.outcomes:
        e.set_feedback_draft(g, o.player_id, "fb")
    e.publish_round(g)
    assert e1 not in e.activities(g)
    assert p1 in e.required_players(g) and not e.may_change(g, p1)


def test_before_and_while_moving_items() -> None:
    """出发前做的排到最前；边走边做的和移动重叠，只算超出路程的部分；一起走的等同伴做完再一起出发。"""
    t = setup_table("single", 2)
    e, g = t.engine, t.game_id
    p0 = t.players[0]
    a = t.entities(p0)[0]
    go = Location(pos=Point(x=50, y=-40))  # 100 米，50 秒
    items = (
        ActionItem(actor=a, verb="go", destination=go),
        ActionItem(actor=a, verb="ask", act_seconds=3, when="before"),
        ActionItem(actor=a, verb="chat", act_seconds=60, when="during"),
        ActionItem(actor=a, verb="look", act_seconds=5),
    )
    intent = Intent(items=items)
    # 3（先问）+ 50（路上聊了 50 秒）+ 10（到了接着聊完）+ 5
    assert e.intent_seconds(g, intent) == 68
    e.declare_action(p0, "x", intent)
    wait(t, t.players[1], 600)
    e.close_round(g)
    act = e.activities(g)[a]
    assert [s.move for s in act.steps] == [0, 50, 0, 0]
    assert [s.act for s in act.steps] == [3, 0, 10, 5]
    assert act.end - act.start == 68
