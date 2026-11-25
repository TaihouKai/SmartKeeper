"""参数（使用时选的数）：效果倍数、选了就执行的句子、能选的条件、被动条目的限时放大；
物品只能通过用途用，开关类用途和开着时的修正；条目和用途自己加的参数。"""

from __future__ import annotations

from typing import Any, cast

import pytest

from smartkeeper.contracts import (
    EntryUse,
    FieldDef,
    GroupDef,
    GroupPreset,
    PackParam,
    ParamDef,
    PatchOp,
    RulePack,
    UseResult,
    ValidationFailed,
)
from smartkeeper.rules import RulesService
from tests.engine.harness import Table, setup_table
from tests.engine.test_timeline import fields_of, publish, wait
from tests.fixtures import load_pack


def param_pack() -> RulePack:
    pack = load_pack("single")
    tpl = pack.templates[0]
    g = tpl.groups[0]
    skills = g.model_copy(
        update={
            "presets": (
                *g.presets,
                GroupPreset(
                    name="hit",
                    fields={"level": 2},
                    config="range = 1000",
                    script="target.damage(2)\nself.add(hp, 0)\nself.sub(hp, 1)",
                ),
                GroupPreset(name="tough", fields={"level": 2}),  # 被动：没有设置也没有脚本
                GroupPreset(
                    name="mark",
                    fields={"level": 1},
                    config='target = "self"',
                    script="self.add(hp, 0)",
                    params=(ParamDef(name="loud", choices=("no=0", "yes=1"), multiplier="5"),),
                ),
            )
        }
    )
    gear = GroupDef(
        name="gear",
        fields=(FieldDef(name="level", kind="number"),),
        uses=True,
        max_count=0,
        presets=(
            GroupPreset(
                name="cloak",
                fields={"level": 1},
                params=(ParamDef(name="quiet", choices=("no=0", "yes=1")),),
                uses=(
                    EntryUse(
                        name="hide",
                        config='target = "self"',
                        script="if turning_on:\n    self.sub(hp, 1)",
                        toggle=True,
                        default_on=True,
                        effects=({"target": "str", "formula": "str + 3"},),  # type: ignore[arg-type]
                    ),
                    EntryUse(
                        name="swing",
                        config="range = 1000",
                        script="target.damage(1)",
                        params=(ParamDef(name="hard", choices=("no=0", "yes=1"), multiplier="3"),),
                    ),
                ),
            ),
        ),
    )
    tpl = tpl.model_copy(update={"groups": (skills, gear, *tpl.groups[1:])})
    both = (g.name, "gear")
    params = (
        PackParam(
            name="power", choices=("no=0", "yes=1"), multiplier="2", duration="10", groups=both
        ),
        PackParam(
            name="pay",
            choices=("no=0", "yes=1"),
            requires="hp > 3",
            script="self.sub(hp, 2)",
            groups=both,
        ),
    )
    return pack.model_copy(update={"templates": (tpl, *pack.templates[1:]), "params": params})


def table() -> tuple[Table, str, str]:
    pack = param_pack()
    assert RulesService().validate_pack(pack) == []
    t = setup_table("single", 2, pack=pack)
    a, b = (t.entities(p)[0] for p in t.players)
    return t, a, b


def begin(t: Table) -> None:
    for p in t.players:
        wait(t, p, 10)
    t.engine.close_round(t.game_id)
    t.engine.begin_plan(t.game_id)


def amounts(ev: Any) -> list[tuple[str, float]]:
    return [(a["op"], a["amount"]) for a in cast(list[dict[str, Any]], ev.payload["actions"])]


def test_multiplier_scales_damage_and_additions_but_not_costs() -> None:
    t, a, b = table()
    begin(t)
    plain = t.engine.use_entry(t.game_id, a, "hit", b, {}, "x")
    strong = t.engine.use_entry(t.game_id, a, "hit", b, {"power": 1}, "x")
    assert plain.payload["boost"] == 1 and strong.payload["boost"] == 2
    raw = {op: v for op, v in amounts(plain)}
    big = {op: v for op, v in amounts(strong)}
    assert big["subtract"] == raw["subtract"]  # 消耗不乘
    damage = [
        x for x in cast(list[dict[str, Any]], strong.payload["actions"]) if x["op"] == "damage"
    ]
    assert damage[0]["raw"] == 4  # 伤害在减免之前乘


def test_param_script_runs_even_on_a_miss_and_requires_is_checked() -> None:
    t, a, b = table()
    begin(t)
    hp = fields_of(t, a)["hp"]
    u = t.engine.use_entry(t.game_id, a, "hit", b, {"pay": 1}, "x")
    publish(t, t.players, uses=[UseResult(seq=u.seq, hit=False)])
    # 选了 pay 扣 2（打没打中都扣），技能自己的 self.sub(hp, 1) 只在命中时算：没检定的技能必中
    assert fields_of(t, a)["hp"] == hp - 3  # type: ignore[operator]
    t.engine.admin_patch(
        t.game_id,
        [PatchOp(op="replace", path=f"/entities/{a}/sheet/fields/hp", value=2)],
    )
    begin(t)
    with pytest.raises(ValidationFailed) as err:
        t.engine.use_entry(t.game_id, a, "hit", b, {"pay": 1}, "x")
    assert err.value.code == "use.param_requires"


def test_passive_entry_is_boosted_for_a_while() -> None:
    t, a, _b = table()
    begin(t)
    u = t.engine.use_entry(t.game_id, a, "tough", None, {"power": 1}, "x")
    assert u.payload["target"] is None  # 只有说明的条目：对象由 KP 给，可以没有
    publish(t, t.players, uses=[UseResult(seq=u.seq)])
    view = t.engine.sheets(t.game_id, t.players[0])[0]
    tough = next(
        x for x in cast(dict[str, Any], view.sheet)["groups"]["skills"] if x["name"] == "tough"
    )
    assert tough["fields"]["level"] == 4


def test_items_are_used_through_their_uses_and_params_add_up() -> None:
    t, a, b = table()
    begin(t)
    with pytest.raises(ValidationFailed) as err:
        t.engine.use_entry(t.game_id, a, "cloak", b, {}, "x")
    assert err.value.code == "use.item_needs_use"
    # 规则包的默认参数 + 物品的 + 用途的：倍数相乘
    u = t.engine.use_entry(t.game_id, a, "cloak/swing", b, {"power": 1, "hard": 1, "quiet": 1}, "x")
    assert u.payload["boost"] == 6
    assert set(cast(dict[str, Any], u.payload["params"])) == {"power", "pay", "quiet", "hard"}
    # 动作类条目自己加的参数
    m = t.engine.use_entry(t.game_id, a, "mark", None, {"loud": 1}, "x")
    assert m.payload["boost"] == 5


def test_toggle_use_starts_on_flips_and_its_modifiers_follow() -> None:
    t, a, _b = table()

    def strength() -> float:
        view = t.engine.sheets(t.game_id, t.players[0])[0]
        d = next((x for x in view.derived if x.name == "str"), None)
        return d.value if d else float(cast(float, fields_of(t, a)["str"]))

    base = float(cast(float, fields_of(t, a)["str"]))
    assert strength() == base + 3  # 一开始就开着
    hp = fields_of(t, a)["hp"]
    begin(t)
    off = t.engine.use_entry(t.game_id, a, "cloak/hide", None, {}, "x")
    assert off.payload["toggle"] == {"key": "cloak/hide", "on": False}
    publish(t, t.players, uses=[UseResult(seq=off.seq)])
    assert strength() == base and fields_of(t, a)["hp"] == hp  # 关上不扣
    begin(t)
    on = t.engine.use_entry(t.game_id, a, "cloak/hide", None, {}, "x")
    publish(t, t.players, uses=[UseResult(seq=on.seq)])
    assert strength() == base + 3 and fields_of(t, a)["hp"] == hp - 1  # type: ignore[operator]


def test_uses_belong_to_item_groups_only() -> None:
    pack = param_pack()
    tpl = pack.templates[0]
    skills = tpl.groups[0]
    odd = skills.model_copy(
        update={"presets": (*skills.presets, GroupPreset(name="multi", uses=(EntryUse(name="a"),)))}
    )
    bad = pack.model_copy(
        update={"templates": (tpl.model_copy(update={"groups": (odd, *tpl.groups[1:])}),)}
    )
    assert "sheet.uses_not_allowed" in {p.code for p in RulesService().validate_pack(bad)}
    gear = tpl.groups[1]
    usable = gear.model_copy(
        update={"presets": (gear.presets[0].model_copy(update={"script": "self.add(hp, 1)"}),)}
    )
    bad = pack.model_copy(
        update={"templates": (tpl.model_copy(update={"groups": (skills, usable)}),)}
    )
    assert "sheet.item_not_usable" in {p.code for p in RulesService().validate_pack(bad)}


def test_text_only_entry_keeps_its_target_and_missing_params_default_to_zero() -> None:
    pack = param_pack()
    free = PackParam(name="ley", groups=("skills",))  # 没有可选值也没有下限
    pack = pack.model_copy(update={"params": (*pack.params, free)})
    t = setup_table("single", 2, pack=pack)
    a, b = (t.entities(p)[0] for p in t.players)
    begin(t)
    u = t.engine.use_entry(t.game_id, a, "tough", b, {}, "x")
    assert u.payload["target"] == b  # 只有说明的条目：对象是 KP 给的那个，不是自己
    assert cast(dict[str, Any], u.payload["params"])["ley"] == 0
