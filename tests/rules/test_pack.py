import json
from typing import Any, cast

import pytest
import sqlalchemy as sa
from pydantic import JsonValue

from smartkeeper.contracts import DerivedDef, FormulaScope, NotFound, RulePack, ValidationFailed
from smartkeeper.rules import RulesService, SqlRulePackStore, export_pack, parse_import
from tests.fixtures import PACKS, load_pack, pack_text

BASE: dict[str, JsonValue] = {
    "name": "X",
    "fields": {"appearance": "a", "occupation": "doctor", "str": 50, "dex": 60, "per": 40},
}


@pytest.mark.parametrize("name", PACKS)
def test_fixture_packs_validate_and_samples_pass(rules: RulesService, name: str) -> None:
    assert rules.validate_pack(load_pack(name)) == []


@pytest.mark.parametrize("name", PACKS)
def test_sample_mismatch_rejected(rules: RulesService, name: str) -> None:
    pack = load_pack(name)
    sample = pack.samples[0]
    key = next(iter(sample.expected))
    bad = sample.model_copy(update={"expected": {**sample.expected, key: sample.expected[key] + 1}})
    pack = pack.model_copy(update={"samples": (bad, *pack.samples[1:])})
    codes = {p.code for p in rules.validate_pack(pack)}
    assert codes == {"pack.sample_mismatch"}


@pytest.mark.parametrize("name", PACKS)
@pytest.mark.parametrize("required", ["perception_radius", "concealment", "move_speed"])
def test_missing_required_derived_rejected(rules: RulesService, name: str, required: str) -> None:
    pack = load_pack(name)
    tpl = pack.templates[0]
    tpl = tpl.model_copy(update={"derived": tuple(d for d in tpl.derived if d.name != required)})
    pack = pack.model_copy(update={"templates": (tpl, *pack.templates[1:])})
    problems = rules.validate_pack(pack)
    assert any(
        p.code == "pack.missing_required_derived" and p.params["name"] == required for p in problems
    )


def test_bad_formula_rejected(rules: RulesService) -> None:
    pack = load_pack("single")
    tpl = pack.templates[0]
    evil = DerivedDef(name="evil", formula="__import__('os')")
    tpl = tpl.model_copy(update={"derived": (*tpl.derived, evil)})
    pack = pack.model_copy(update={"templates": (tpl,)})
    assert rules.validate_pack(pack)


def test_unknown_name_in_formula(rules: RulesService) -> None:
    pack = load_pack("single")
    codes = [p.code for p in rules.validate_formula(pack, "person", "str + nope")]
    assert codes == ["formula.unknown_name"]
    assert rules.validate_formula(pack, "person", "str + per * 2") == []
    assert rules.validate_formula(pack, "person", "this.level * 2", in_entry="skills") == []
    assert rules.validate_formula(pack, "person", "this.level * 2") != []


def test_derived_cycle_rejected(rules: RulesService) -> None:
    pack = load_pack("single")
    tpl = pack.templates[0]
    derived = (*tpl.derived, DerivedDef(name="loop", formula="loop + 1"))
    pack = pack.model_copy(update={"templates": (tpl.model_copy(update={"derived": derived}),)})
    assert any(p.code == "formula.cycle" for p in rules.validate_pack(pack))


def test_cycle_found_without_samples(rules: RulesService) -> None:
    pack = load_pack("single")
    tpl = pack.templates[0]
    derived = (
        *tpl.derived,
        DerivedDef(name="a", formula="b + 1"),
        DerivedDef(name="b", formula="a * 2"),
    )
    tpl = tpl.model_copy(update={"derived": derived})
    pack = pack.model_copy(update={"templates": (tpl,), "samples": ()})
    cycles = [p for p in rules.validate_pack(pack) if p.code == "formula.cycle"]
    assert len(cycles) == 1 and cycles[0].params["name"] == "a -> b -> a"


def test_mechanical_and_conceptual_effects(rules: RulesService) -> None:
    pack = load_pack("single")
    plain = rules.derived_value(pack, "person", BASE, "perception_radius")
    conceptual: dict[str, JsonValue] = {
        **BASE,
        "groups": {
            "skills": [{"name": "s", "fields": {"level": 1}, "effects": [{"description": "x"}]}]
        },
    }
    assert rules.derived_value(pack, "person", conceptual, "perception_radius") == plain
    mech: dict[str, JsonValue] = {
        **BASE,
        "groups": {
            "skills": [
                {
                    "name": "s",
                    "fields": {"level": 1},
                    "effects": [{"target": "perception_radius", "op": "mul", "value": "2"}],
                }
            ]
        },
    }
    assert rules.derived_value(pack, "person", mech, "perception_radius") == plain * 2


def test_statuses_chain_in_the_order_added(rules: RulesService) -> None:
    pack = load_pack("single")
    sheet: dict[str, JsonValue] = {
        **BASE,
        "statuses": [
            {
                "tag": "focused",
                "modifier": {"target": "perception_radius", "formula": "perception_radius * 2"},
            },
            {
                "tag": "lantern",
                "modifier": {"target": "perception_radius", "formula": "perception_radius + 10"},
            },
        ],
    }
    assert rules.derived_value(pack, "person", sheet, "perception_radius") == 90 * 2 + 10


def test_legacy_add_mul_effects_still_load(rules: RulesService) -> None:
    pack = load_pack("single")
    sheet: dict[str, JsonValue] = {
        **BASE,
        "statuses": [
            {"tag": "old", "modifier": {"target": "perception_radius", "op": "mul", "value": "2"}}
        ],
    }
    assert rules.derived_value(pack, "person", sheet, "perception_radius") == 180


def skill(name: str, formula: str, priority: int | None) -> dict[str, JsonValue]:
    eff: dict[str, JsonValue] = {"target": "move_speed", "formula": formula}
    if priority is not None:
        eff["priority"] = priority
    return {"name": name, "fields": {"level": 1}, "effects": [eff]}


def test_player_effects_run_by_priority_and_may_use_anything(rules: RulesService) -> None:
    pack = load_pack("single")
    # move_speed = 60 + dex(60) = 120
    sheet: dict[str, JsonValue] = {
        **BASE,
        "groups": {
            "skills": [
                skill("double", "move_speed * 2", 1),
                skill("rewrite", "str + dex", 0),  # 先算：完全不管原值
            ]
        },
        "statuses": [
            {"tag": "hurt", "modifier": {"target": "move_speed", "formula": "move_speed - per"}}
        ],
    }
    # 玩家技能按 priority：str + dex = 110，再 × 2 = 220；最后状态：220 - per(40) = 180
    assert rules.derived_value(pack, "person", sheet, "move_speed") == 180
    filled = rules.init_sheet(pack, "person", sheet)
    assert rules.validate_sheet(pack, "person", filled) == []


def test_player_effect_priority_required_and_unique(rules: RulesService) -> None:
    pack = load_pack("single")

    def codes(*skills: dict[str, JsonValue]) -> set[str]:
        sheet = rules.init_sheet(pack, "person", {**BASE, "groups": {"skills": list(skills)}})
        return {p.code for p in rules.validate_sheet(pack, "person", sheet)}

    assert "sheet.effect_priority_missing" in codes(skill("a", "move_speed + 1", None))
    assert "sheet.effect_priority_duplicate" in codes(
        skill("a", "move_speed + 1", 3), skill("b", "move_speed * 2", 3)
    )


def test_sheet_validation(rules: RulesService) -> None:
    pack = load_pack("single")
    good = rules.init_sheet(pack, "person", pack.samples[0].sheet)
    assert rules.validate_sheet(pack, "person", good) == []
    assert isinstance(good, dict)
    fields = good["fields"]
    assert isinstance(fields, dict)
    assert fields["hp"] == 11

    def codes(**changes: JsonValue) -> set[str]:
        sheet: dict[str, JsonValue] = {**good, "fields": {**fields, **changes}}
        return {p.code for p in rules.validate_sheet(pack, "person", sheet)}

    assert codes(hp=12) == {"sheet.above_max"}
    assert codes(hp=-1) == {"sheet.below_min"}
    assert codes(nope=1) == {"sheet.unknown_field"}
    assert codes(perception_radius=500) == {"sheet.derived_not_writable"}
    assert codes(str="strong") == {"sheet.type"}
    assert codes(occupation="pirate") == {"sheet.choice"}


@pytest.mark.parametrize("name", PACKS)
def test_render_contains_rules_text(rules: RulesService, name: str) -> None:
    pack = load_pack(name)
    text = rules.render(pack)
    assert pack.rules_text in text
    for t in pack.templates:
        assert t.name in text


# ---- 存储、版本、导入导出 ----


@pytest.fixture
def store(rules: RulesService) -> SqlRulePackStore:
    return SqlRulePackStore(sa.create_engine("sqlite://"), rules)


def test_versions_are_immutable(store: SqlRulePackStore) -> None:
    pid = store.create_pack("x")
    v1 = store.save_version(pid, load_pack("single"))
    changed = load_pack("single").model_copy(update={"rules_text": "changed"})
    v2 = store.save_version(pid, changed)
    assert (v1.version, v2.version) == (1, 2)
    assert store.get_version(pid, 1).pack.rules_text != "changed"
    assert store.get_version(pid, 2).pack.rules_text == "changed"
    store.delete_version(pid, 1)
    assert store.list_packs()[0].versions == (2,)


def test_invalid_pack_not_saved(store: SqlRulePackStore) -> None:
    pid = store.create_pack("x")
    pack = load_pack("single")
    tpl = pack.templates[0].model_copy(update={"derived": ()})
    with pytest.raises(ValidationFailed):
        store.save_version(pid, pack.model_copy(update={"templates": (tpl,)}))
    assert store.list_packs() == []  # 没有版本也没有草稿的规则包不列出


def test_drafts_skip_validation_and_clear_on_save(store: SqlRulePackStore) -> None:
    pid = store.create_pack("x")
    pack = load_pack("single")
    unfinished = pack.model_copy(update={"templates": (), "checks": ()})
    d = store.save_draft(pid, unfinished)
    assert store.get_draft(pid).pack == unfinished
    info = store.list_packs()[0]
    assert info.versions == () and info.draft_updated_at == d.updated_at
    store.save_draft(pid, pack)  # 覆盖
    assert store.get_draft(pid).pack == pack
    store.save_version(pid, pack)
    assert store.list_packs()[0].draft_updated_at is None
    with pytest.raises(NotFound):
        store.get_draft(pid)


def test_deleting_a_draft_of_an_unsaved_pack_removes_the_pack(store: SqlRulePackStore) -> None:
    pid = store.create_pack("x")
    store.save_draft(pid, load_pack("single"))
    store.delete_draft(pid)
    assert store.list_packs() == []


@pytest.mark.parametrize("name", PACKS)
def test_export_import_roundtrip(name: str) -> None:
    pack = load_pack(name)
    assert parse_import(export_pack(pack)) == pack
    assert parse_import(pack_text(name)) == pack


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        "[]",
        json.dumps({"format": "other"}),
        json.dumps({"format": "smartkeeper.rulepack", "format_version": 9, "pack": {}}),
        json.dumps({"format": "smartkeeper.rulepack", "format_version": 1, "pack": {"world": {}}}),
    ],
)
def test_malformed_import_rejected(text: str) -> None:
    with pytest.raises(ValidationFailed):
        parse_import(text)


def test_invalid_import_rejected_by_save(store: SqlRulePackStore) -> None:
    body = json.loads(pack_text("single"))
    body["pack"]["templates"][0]["derived"] = []
    pack = parse_import(json.dumps(body))
    with pytest.raises(ValidationFailed):
        store.save_version(store.create_pack("x"), pack)


def test_pack_type_roundtrip() -> None:
    pack = load_pack("multi")
    assert RulePack.model_validate_json(pack.model_dump_json()) == pack


def test_can_fly_is_a_required_boolean_field(rules: RulesService) -> None:
    pack = load_pack("single")
    tpl = pack.templates[0]
    tpl = tpl.model_copy(update={"fields": tuple(f for f in tpl.fields if f.name != "can_fly")})
    pack = pack.model_copy(update={"templates": (tpl, *pack.templates[1:])})
    assert "pack.missing_can_fly" in {p.code for p in rules.validate_pack(pack)}


def test_boolean_field_defaults_to_false_and_checks_type(rules: RulesService) -> None:
    pack = load_pack("single")
    filled = rules.init_sheet(pack, "person", BASE)
    assert isinstance(filled, dict)
    assert filled["fields"]["can_fly"] is False  # type: ignore[index]
    bad = {**BASE, "fields": {**BASE["fields"], "can_fly": "yes"}}  # type: ignore[dict-item]
    codes = {
        p.code for p in rules.validate_sheet(pack, "person", rules.init_sheet(pack, "person", bad))
    }
    assert "sheet.type" in codes


def test_formula_field_values_are_checked_and_may_roll(rules: RulesService) -> None:
    from smartkeeper.contracts import FieldDef

    pack = load_pack("single")
    tpl = pack.templates[0]
    g = tpl.groups[0]
    g = g.model_copy(update={"fields": (*g.fields, FieldDef(name="damage", kind="formula"))})
    tpl = tpl.model_copy(update={"groups": (g,)})
    pack = pack.model_copy(update={"templates": (tpl,), "samples": ()})
    assert rules.validate_pack(pack) == []

    def codes(damage: str) -> set[str]:
        skill: dict[str, JsonValue] = {"name": "hit", "fields": {"level": 3, "damage": damage}}
        sheet = rules.init_sheet(pack, "person", {**BASE, "groups": {"skills": [skill]}})
        return {p.code for p in rules.validate_sheet(pack, "person", sheet)}

    assert codes("1d str") == set()
    assert codes("dice(this.level, 6) + floor(str / 10)") == set()
    assert "formula.unknown_name" in codes("1d nope")
    assert (
        rules.validate_formula(
            pack, "person", "dice(this.level, 6)", in_entry="skills", scope="dice"
        )
        == []
    )


def test_params_apply_to_groups_and_spend_a_number(rules: RulesService) -> None:
    from smartkeeper.contracts import PackParam

    pack = load_pack("single")
    g = pack.templates[0].groups[0]
    good = pack.model_copy(
        update={
            "params": (
                PackParam(name="cost", min="1", max="this.level", spends="hp", groups=(g.name,)),
            )
        }
    )
    assert rules.validate_pack(good) == []
    bad_target = pack.model_copy(
        update={"params": (PackParam(name="cost", spends="occupation", groups=(g.name,)),)}
    )
    assert "pack.unknown_spend_target" in {p.code for p in rules.validate_pack(bad_target)}
    nowhere = pack.model_copy(update={"params": (PackParam(name="cost", groups=("nope",)),)})
    assert "pack.unknown_group" in {p.code for p in rules.validate_pack(nowhere)}
    clash = pack.model_copy(update={"params": (PackParam(name="level", groups=(g.name,)),)})
    assert "pack.param_name_clash" in {p.code for p in rules.validate_pack(clash)}


def test_old_param_columns_move_to_default_params() -> None:
    from smartkeeper.contracts import RulePack

    raw = load_pack("single").model_dump(mode="json")
    g = raw["templates"][0]["groups"][0]
    g["fields"].append({"name": "cost", "kind": "param", "min": "1", "spends": "hp", "check": None})
    pack = RulePack.model_validate(raw)
    assert [x.name for x in pack.templates[0].groups[0].fields] == ["level"]
    assert pack.params[0].name == "cost" and pack.params[0].spends == "hp"
    assert pack.params[0].groups == (g["name"],)


def test_self_is_your_own_value(rules: RulesService) -> None:
    pack = load_pack("single")
    assert rules.validate_formula(pack, "person", "self.str + str") == []
    assert [p.code for p in rules.validate_formula(pack, "person", "self.nope")] == [
        "formula.unknown_name"
    ]


def test_script_validation(rules: RulesService) -> None:
    pack = load_pack("single")

    def codes(text: str) -> list[tuple[str, object]]:
        got = rules.validate_formula(pack, "person", text, in_entry="skills", scope="script")
        return [(p.code, p.params.get("line")) for p in got]

    assert codes("target.damage(dice(this.level, 6))\nself.add(hp, 1, 10)") == []
    assert codes("target.modify(move_speed, move_speed * 0.5, 1)") == []
    assert codes("self.add(str, 1)") == [("script.not_runtime", 1)]
    assert codes("\ntarget.modify(hp, 1, 1)") == [("script.not_derived", 2)]
    assert codes("target.damage(nope)") == [("formula.unknown_name", 1)]
    assert codes("target.modify(move_speed, 1d6, 1)") == [("formula.dice_not_allowed", 1)]
    assert codes("self.fly(1)") == [("script.unknown_verb", 1)]
    branchy = 'if target.template == "person":\n  self.add(hp, 1)\nelse:\n  self.add(str, 1)'
    assert codes(branchy) == [("script.not_runtime", 4)]
    assert codes("if 1d6 > 3:\n  self.add(hp, 1)") == [("formula.dice_not_allowed", 1)]
    assert codes("if nope:\n  self.add(hp, 1)") == [("formula.unknown_name", 1)]


def test_skill_config_validation(rules: RulesService) -> None:
    pack = load_pack("single")

    def codes(text: str) -> list[tuple[str, object]]:
        got = rules.validate_formula(pack, "person", text, in_entry="skills", scope="config")
        return [(p.code, p.params.get("line")) for p in got]

    good = 'target = "single"\nrange = 10 + this.level\nvisible = True\nnoise = None\ncooldown = 60'
    assert codes(good) == []
    assert codes('target = "everyone"') == [("config.bad_value", 1)]
    assert codes("\nreach = 5") == [("config.unknown_key", 2)]
    assert codes("range = 1\nrange = 2") == [("config.duplicate", 2)]
    assert codes("range = nope") == [("formula.unknown_name", 1)]
    assert codes("range = 1d6") == [("formula.dice_not_allowed", 1)]
    assert codes("visible = 3") == [("config.bad_value", 1)]
    assert codes("shape = blob(radius=1)") == [("config.bad_call", 1)]
    assert codes("shape = sphere(length=1)") == [("config.bad_arg", 1)]
    assert codes("x == 1") == [("config.bad_line", 1)]
    cfg = rules.skill_config(
        "shape = cone(length=10, angle=60)\nplacement = placement(radius=3, duration=2)"
    )
    assert cfg.shape is not None and cfg.shape.kind == "cone" and cfg.shape.angle == 60
    assert cfg.placement is not None and cfg.placement.duration == "(2) * 60"
    assert rules.skill_config("").target == "single"


def test_boolean_initial_must_look_like_a_boolean(rules: RulesService) -> None:
    from smartkeeper.contracts import FieldDef

    pack = load_pack("single")
    tpl = pack.templates[0]

    def codes(initial: str) -> list[str]:
        fd = FieldDef(name="silenced", kind="boolean", cls="runtime", initial=initial)
        p = pack.model_copy(
            update={"templates": (tpl.model_copy(update={"fields": (*tpl.fields, fd)}),)}
        )
        return [x.code for x in rules.validate_pack(p) if x.code == "pack.boolean_initial"]

    assert codes("123") == ["pack.boolean_initial"]
    assert codes('"yes"') == ["pack.boolean_initial"]
    assert codes("False") == codes("1") == codes("str > 3") == []


def test_settings_and_scripts_may_use_earlier_names(rules: RulesService) -> None:
    pack = load_pack("single")

    def codes(text: str, scope: FormulaScope) -> list[tuple[str, object]]:
        got = rules.validate_formula(pack, "person", text, in_entry="skills", scope=scope)
        return [(p.code, p.params.get("line")) for p in got]

    # 设置：后面的项引用前面的项；引用下面的项不行（和 Python 一样）
    assert codes("range = 10 + this.level\nnoise = range * 2", "config") == []
    # 不分先后，但不能绕成圈
    assert codes("noise = range\nrange = 10", "config") == []
    assert codes("range = noise\nnoise = range", "config")[0][0] == "formula.cycle"
    assert rules.skill_config("range = 10\nnoise = range * 2").noise == "10 * 2"
    # 脚本：局部变量；不能掷骰
    script = "heal = 2 + this.level\nif heal > 1:\n    self.add(hp, heal)\ntarget.modify(move_speed, move_speed + heal, 1)"
    assert codes(script, "script") == []
    assert codes("x = 1d6\nself.add(hp, x)", "script") == [("formula.dice_not_allowed", 1)]
    assert codes("self.add(hp, y)\ny = 1", "script") == [("formula.unknown_name", 1)]


def test_script_variables_are_worked_out_once(rules: RulesService) -> None:
    from tests.fixtures import FakeDice

    pack = load_pack("single")
    sheet = rules.init_sheet(pack, "person", pack.samples[0].sheet)
    script = "heal = 2 + this.level * 3\nself.add(hp, heal)\nif heal > 100:\n    self.damage(1)\ntarget.modify(move_speed, move_speed + heal, 1)"
    steps = rules.plan_script(
        pack, script, FakeDice().faces, "person", sheet, {"level": 2}, None, ("person", sheet, None)
    )
    assert [(s.op, s.amount) for s in steps[:1]] == [("add", 8)]
    assert len(steps) == 2 and steps[1].formula == "move_speed + 8"


def test_settings_and_script_see_each_other(rules: RulesService) -> None:
    from tests.fixtures import FakeDice

    pack = load_pack("single")

    def codes(text: str, scope: FormulaScope, other: str) -> list[str]:
        got = rules.validate_formula(
            pack, "person", text, in_entry="skills", scope=scope, other=other
        )
        return [p.code for p in got]

    script = "reach = 5 + this.level\ntarget.damage(range)"
    config = "range = reach * 2"
    # 设置用脚本的变量，脚本用设置的项
    assert codes(config, "config", script) == []
    assert codes(script, "script", config) == []
    assert codes(config, "config", "") == ["formula.unknown_name"]
    # 脚本变量不能和设置项同名
    assert codes("range = 1\nself.add(hp, range)", "script", "") == ["script.setting_name"]
    assert rules.skill_config(config, script).range == "(5 + this.level) * 2"
    sheet = rules.init_sheet(pack, "person", pack.samples[0].sheet)
    steps = rules.plan_script(
        pack,
        script,
        FakeDice().faces,
        "person",
        sheet,
        {"level": 1},
        None,
        ("person", sheet, None),
        config,
    )
    assert [(x.op, x.amount) for x in steps] == [("damage", 12)]


def test_skill_config_checks_must_exist(rules: RulesService) -> None:
    pack = load_pack("single")

    def codes(text: str) -> list[tuple[str, object]]:
        got = rules.validate_formula(pack, "person", text, in_entry="skills", scope="config")
        return [(p.code, p.params.get("line")) for p in got]

    assert codes('check = "spot"\nreactions = ["struggle"]\ndifficulty = 10 + this.level') == []
    assert codes('check = "nope"') == [("config.unknown_check", 1)]
    # reactions 里可以是检定或写好的应对技能
    assert codes('\nreactions = ["spot", "nope"]') == [("config.unknown_reaction", 2)]
    assert codes("reactions = [1]") == [("config.list_of_text", 1)]
    assert (
        codes('check = best("spot", "struggle")\nreactions = True\nhit = level > opp_level') == []
    )
    assert codes('check = best("spot", "nope")') == [("config.unknown_check", 1)]
    assert codes('save = "nope"') == [("config.unknown_check", 1)]
    assert codes("difficulty = floor(distance / 500)\nauto_level = 2 if unseen else 1") == []
    assert [c for c, _ in codes("difficulty = opp_level")] == ["formula.unknown_name"]


def test_number_choices(rules: RulesService) -> None:
    from smartkeeper.contracts import FieldDef

    pack = load_pack("single")
    tpl = pack.templates[0]

    def with_field(choices: tuple[str, ...]) -> RulePack:
        fd = FieldDef(name="rank", kind="number", choices=choices)
        return pack.model_copy(
            update={"templates": (tpl.model_copy(update={"fields": (*tpl.fields, fd)}),)}
        )

    bad = with_field(("E=1", "D=", "1~x"))
    assert [
        p.params["item"] for p in rules.validate_pack(bad) if p.code == "pack.bad_number_choice"
    ] == ["D="]
    good = with_field(("E=1", "D=2", "C=3", "B=4", "A=5", "EX=10"))
    sheet = pack.samples[0].sheet

    def codes(value: object) -> list[str]:
        s = {**sheet, "fields": {**sheet["fields"], "rank": value}}  # type: ignore[dict-item]
        return [p.code for p in rules.validate_sheet(good, "person", s)]

    assert "sheet.choice" not in codes(10) and "sheet.choice" not in codes(3)
    assert "sheet.choice" in codes(7)
    ranged = with_field(("1~5", "10"))
    s = {**sheet, "fields": {**sheet["fields"], "rank": 6}}  # type: ignore[dict-item]
    assert "sheet.choice" in [p.code for p in rules.validate_sheet(ranged, "person", s)]


def test_damage_kinds_and_damage_taken(rules: RulesService) -> None:
    from tests.fixtures import FakeDice

    pack = load_pack("single")
    tpl = pack.templates[0]
    tpl = tpl.model_copy(
        update={"damage_taken": 'max(0, amount - 5 * per / 10) if kind == "magic" else amount'}
    )
    pack = pack.model_copy(update={"templates": (tpl, *pack.templates[1:])})
    assert rules.validate_pack(pack) == []
    sheet = rules.init_sheet(pack, "person", pack.samples[0].sheet)  # per = 40：魔力伤害减 20
    tgt = ("person", sheet, None)

    def plan(script: str, kind: str = "") -> list[tuple[float, str, float | None]]:
        steps = rules.plan_script(
            pack, script, FakeDice().faces, "person", sheet, {}, None, tgt, "", None, kind
        )
        return [(s.amount, s.kind, s.raw) for s in steps]

    assert plan("target.damage(30)") == [(30, "", 30)]
    assert plan("target.damage(30)", kind="magic") == [(10, "magic", 30)]  # 分组的类型
    assert plan('target.damage(15, "magic")') == [(0, "magic", 15)]  # 单独指定；不会小于 0
    assert plan('target.damage(30, "physical")', kind="magic") == [(30, "physical", 30)]
    bad = rules.validate_formula(pack, "person", "amount * nope", None, "damage")
    assert [p.code for p in bad] == ["formula.unknown_name"]


def test_preset_columns_left_empty_are_filled_by_the_player(rules: RulesService) -> None:
    from smartkeeper.contracts import GroupPreset

    pack = load_pack("single")
    tpl = pack.templates[0]
    g = tpl.groups[0].model_copy(
        update={
            "presets": (
                GroupPreset(name="resist", id="resist"),  # level 留空：玩家填
                GroupPreset(name="fixed", id="fixed", fields={"level": 7}),
                GroupPreset(name="tall", id="tall", when="str > 90"),  # 不生效：不用填
            )
        }
    )
    tpl = tpl.model_copy(update={"groups": (g,)})
    pack = pack.model_copy(update={"templates": (tpl, *pack.templates[1:])})
    # 例题卡没填 resist 的 level：规则包检查会指出来
    assert "samples[0].preset_fields.skills.resist.level" in [
        p.path for p in rules.validate_pack(pack)
    ]
    base = pack.samples[0].sheet

    def check(preset_fields: dict[str, Any]) -> list[tuple[str, str]]:
        sheet = rules.init_sheet(pack, "person", {**base, "preset_fields": preset_fields})
        return [(p.code, p.path) for p in rules.validate_sheet(pack, "person", sheet)]

    assert check({}) == [("sheet.missing_field", "preset_fields.skills.resist.level")]
    assert check({"skills": {"resist": {"level": 30}}}) == []
    assert check({"skills": {"fixed": {"level": 3}}})[0] == (
        "sheet.unknown_field",
        "preset_fields.skills.fixed.level",
    )
    sheet = rules.init_sheet(
        pack, "person", {**base, "preset_fields": {"skills": {"resist": {"level": 30}}}}
    )
    full = cast(dict[str, Any], rules.full_sheet(pack, "person", sheet))
    levels = {e["name"]: e["fields"].get("level") for e in full["groups"]["skills"]}
    assert levels == {"resist": 30, "fixed": 7, "first aid": 30}
