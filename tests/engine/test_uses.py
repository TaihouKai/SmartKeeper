"""条目的用途、使用时的参数（可选值、检定、冷却）、条目自己的运行中的列、修正字段，
以及范围技能、召唤、瞬间移动、整栋建筑的设置物。"""

from __future__ import annotations

from typing import Any, cast

import pytest

from smartkeeper.contracts import (
    CheckDef,
    EntryUse,
    FieldDef,
    GroupDef,
    GroupPreset,
    PackParam,
    PatchOp,
    RulePack,
    ShapeDef,
    UseResult,
    ValidationFailed,
)
from smartkeeper.rules import RulesService
from tests.engine.harness import Table, setup_table
from tests.engine.test_timeline import fields_of, publish, wait
from tests.fixtures import load_pack


def kit_pack() -> RulePack:
    """skills 分组：几个动作（范围、召唤、瞬间移动、飞行、整栋建筑的设置物）；gear 分组是物品类：kit 有几种用途。
    默认参数 mode / boost / lucky 适用于这两个分组。"""
    pack = load_pack("single")
    tpl = pack.templates[0]
    g = tpl.groups[0]
    gear_cols = (
        *g.fields,
        FieldDef(name="on", kind="boolean", cls="runtime", required=False),
        FieldDef(name="charges", kind="number", cls="runtime", initial="3", required=False),
    )
    kit = GroupPreset(
        name="kit",
        fields={"level": 2},
        effects=(
            # 开着的时候 str + 2：修正作用在建角时填的字段上
            {"target": "str", "formula": "str + 2 if this.on else str"},  # type: ignore[arg-type]
        ),
        uses=(
            EntryUse(
                name="zap", config="range = 1000", script="target.damage(2 if this.mode else 1)"
            ),
            EntryUse(
                name="arm",
                config='target = "self"',
                script="self.set(this.on, 1)\nself.sub(this.charges, 1)",
            ),
            EntryUse(
                name="hype",
                config='target = "self"',
                script="self.modify(this.level, this.level * 3, 10)",
            ),
            EntryUse(name="try", config='target = "self"', script="self.add(hp, 0)"),
            EntryUse(name="sense", description="KP 按说明裁定"),
        ),
    )
    presets = (
        GroupPreset(
            name="burst",
            fields={"level": 1},
            config="shape = sphere(radius=500)",
            script="target.damage(1)\nself.sub(hp, 1)",
        ),
        GroupPreset(
            name="call",
            fields={"level": 1},
            config='target = "self"',
            script='self.summon(person, 2, 1, appearance="imp", occupation="doctor", str=1, dex=1, per=1)',
        ),
        GroupPreset(name="recall", fields={"level": 1}, script="target.teleport(self)"),
        GroupPreset(
            name="fly",
            fields={"level": 1},
            config='target = "self"',
            script="self.modify(can_fly, 1, 10)",
        ),
        GroupPreset(
            name="camp",
            fields={"level": 1},
            config='target = "none"\nplacement = placement(building=True, perceive=0)',
        ),
    )
    skills = g.model_copy(
        update={
            "presets": (*g.presets, *presets),
            "shapes": ShapeDef(allowed=("sphere",)),
            "placements": True,
        }
    )
    gear = GroupDef(name="gear", fields=gear_cols, presets=(kit,), uses=True, max_count=0)
    tpl = tpl.model_copy(update={"groups": (skills, gear, *tpl.groups[1:])})
    checks = (
        *pack.checks,
        CheckDef(name="never", config="dice = 1d1\nsuccess = roll > 5"),
        CheckDef(name="always", config="dice = 1d1\nsuccess = roll >= 1"),
    )
    both = ("skills", "gear")
    params = (
        PackParam(name="mode", choices=("off=0", "on=1"), groups=both),
        PackParam(
            name="boost", choices=("no=0", "yes=1"), check="never", cooldown="60", groups=both
        ),
        PackParam(name="lucky", choices=("no=0", "yes=1"), check="always", groups=both),
    )
    return pack.model_copy(
        update={"templates": (tpl, *pack.templates[1:]), "checks": checks, "params": params}
    )


def table() -> tuple[Table, str, str]:
    pack = kit_pack()
    assert RulesService().validate_pack(pack) == []
    t = setup_table("single", 2, pack=pack)
    a, b = (t.entities(p)[0] for p in t.players)
    return t, a, b


def begin(t: Table, seconds: int = 10) -> None:
    for p in t.players:
        wait(t, p, seconds)
    t.engine.close_round(t.game_id)
    t.engine.begin_plan(t.game_id)


def params(ev: Any) -> dict[str, Any]:
    return cast(dict[str, Any], ev.payload["params"])


def state(t: Table) -> dict[str, Any]:
    return cast(dict[str, Any], t.engine.world_state(t.game_id))


def kit(t: Table, eid: str) -> dict[str, Any]:
    sheet = t.engine.sheets(t.game_id, t.players[0])[0].sheet
    return next(e for e in cast(dict[str, Any], sheet)["groups"]["gear"] if e["name"] == "kit") | {
        "_": eid
    }


def test_a_use_inherits_the_entrys_config_and_reads_its_columns() -> None:
    t, a, b = table()
    begin(t)
    e, g = t.engine, t.game_id
    hp = fields_of(t, b)["hp"]
    u = e.use_entry(g, a, "kit/zap", b, {"mode": 1}, "x")
    assert u.payload["entry"] == "kit/zap" and u.payload["owner_entry"] == "kit"
    assert params(u)["mode"] == 1
    plain = e.use_entry(g, a, "kit/zap", b, {}, "x")  # 有可选值的参数没给：取第一个
    assert params(plain)["mode"] == 0
    with pytest.raises(ValidationFailed) as err:
        e.use_entry(g, a, "kit/zap", b, {"mode": 5}, "x")
    assert err.value.code == "roll.param_not_a_choice"
    # 只写说明的用途：记下这次使用，效果由 KP 裁定
    sense = e.use_entry(g, a, "kit/sense", b, {}, "x")
    assert sense.payload["actions"] == []
    publish(t, only=t.players, uses=[UseResult(seq=x.seq) for x in (u, plain, sense)])
    assert fields_of(t, b)["hp"] == hp - 3  # type: ignore[operator]


def test_option_check_and_cooldown() -> None:
    t, a, b = table()
    begin(t)
    e, g = t.engine, t.game_id
    u = e.use_entry(g, a, "kit/zap", b, {"boost": 1, "lucky": 1}, "x")
    # 没过检定的选项按没选算；过了的照旧
    assert params(u)["boost"] == 0 and params(u)["lucky"] == 1
    assert list(cast(dict[str, Any], u.payload["param_cooldowns"])) == ["cooldown:kit#boost"]
    publish(t, only=t.players, uses=[UseResult(seq=u.seq)])
    begin(t)
    with pytest.raises(ValidationFailed) as err:
        e.use_entry(g, a, "kit/zap", b, {"boost": 1}, "x")
    assert err.value.code == "use.param_cooling_down"
    e.use_entry(g, a, "kit/zap", b, {"boost": 0}, "x")  # 不选这个选项就能用


def test_entry_columns_change_and_feed_its_effects() -> None:
    t, a, _b = table()
    begin(t)
    e, g = t.engine, t.game_id
    base = fields_of(t, a)["str"]
    u = e.use_entry(g, a, "kit/arm", None, {}, "x")
    h = e.use_entry(g, a, "kit/hype", None, {}, "x")
    publish(t, only=t.players, uses=[UseResult(seq=u.seq), UseResult(seq=h.seq)])
    stored = state(t)["entities"][a]["sheet"]["preset_fields"]["gear"]["kit"]
    assert stored == {"on": True, "charges": 2}
    view = next(v for v in e.sheets(g, t.players[0]) if v.entity_id == a)
    live = next(x for x in cast(dict[str, Any], view.sheet)["groups"]["gear"] if x["name"] == "kit")
    assert live["fields"]["level"] == 6  # 限时修正 kit.level × 3
    strength = next(d for d in view.derived if d.name == "str")
    assert strength.base == base and strength.value == base + 2  # type: ignore[operator]


def test_area_hits_everyone_in_the_shape_and_costs_once() -> None:
    t, a, b = table()
    begin(t)
    e, g = t.engine, t.game_id
    hp_a, hp_b = fields_of(t, a)["hp"], fields_of(t, b)["hp"]
    hp_npc = cast(float, fields_of(t, "npc_1")["hp"])
    u = e.use_entry(g, a, "burst", b, {}, "x")
    others = [x for x in e.planned_uses(g) if cast(dict[str, Any], x)["area_of"] == u.seq]
    assert u.payload["target"] == b
    assert {cast(dict[str, Any], x)["target"] for x in others} == {"npc_1"}
    # 这个技能不能应对：不等对象，直接算
    publish(t, only=t.players, uses=[UseResult(seq=u.seq)])
    assert fields_of(t, b)["hp"] == hp_b - 1  # type: ignore[operator]
    assert fields_of(t, a)["hp"] == hp_a - 1  # type: ignore[operator]  # 对自己的只算一次
    assert cast(float, fields_of(t, "npc_1")["hp"]) == hp_npc - 1


def test_summon_teleport_and_flight() -> None:
    t, a, b = table()
    begin(t)
    e, g = t.engine, t.game_id
    c = e.use_entry(g, a, "call", None, {}, "x")
    r = e.use_entry(g, a, "recall", b, {}, "x")
    fl = e.use_entry(g, a, "fly", None, {}, "x")
    publish(t, only=t.players, uses=[UseResult(seq=x.seq) for x in (c, r, fl)])
    s = state(t)
    imps = [k for k, v in s["entities"].items() if v.get("summoned", {}).get("by") == a]
    assert len(imps) == 2 and set(imps) <= set(s["controls"][t.players[0]])
    assert s["entities"][b]["pos"] == s["entities"][a]["pos"]
    assert e._space(g).derived(a, "can_fly") == 1  # pyright: ignore[reportPrivateUsage]
    begin(t, seconds=120)  # 召唤物存在 1 分钟
    publish(t, only=t.players)
    s = state(t)
    assert not any(v.get("summoned") for v in s["entities"].values())
    assert not set(imps) & set(s["controls"][t.players[0]])


def test_a_whole_building_as_placement() -> None:
    t, a, _b = table()
    e, g = t.engine, t.game_id
    e.admin_patch(
        g,
        [
            PatchOp(op="replace", path=f"/entities/{a}/pos", value={"x": 10, "y": 10, "z": 0}),
            PatchOp(op="replace", path=f"/entities/{a}/inside", value="bldg_tower"),
        ],
    )
    from smartkeeper.contracts import PlaceIn, Point

    for p in t.players:
        wait(t, p, 10)
    e.close_round(g)
    item = e.activities(g)[a].steps[0].item
    pin = PlaceIn(owner=a, entry="camp", at=Point(x=0, y=0, z=0), because=item)
    publish(t, only=t.players, placements=[pin])
    s = state(t)
    placed = next(iter(s["placements"].values()))
    assert placed["building"] == "bldg_tower"
    # 站在自己的据点里：in:camp 状态，公式里 inside("camp")
    tags = {x["tag"] for x in s["entities"][a]["sheet"]["statuses"]}
    assert "in:camp" in tags
