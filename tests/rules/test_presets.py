"""分组的固定条目：条件为真时出现在角色卡上，带的效果算进推导值；不存进卡，也不算进条目数量。"""

from typing import Any

from pydantic import JsonValue

from smartkeeper.contracts import GroupPreset, RulePack
from smartkeeper.rules import RulesService
from tests.fixtures import load_pack

BASE: dict[str, JsonValue] = {
    "name": "X",
    "fields": {"appearance": "a", "occupation": "doctor", "str": 50, "dex": 60, "per": 40},
}


def with_presets(*presets: dict[str, Any]) -> RulePack:
    pack = load_pack("single")
    tpl = pack.templates[0]
    g = next(g for g in tpl.groups if g.name == "skills")
    g = g.model_copy(update={"presets": tuple(GroupPreset.model_validate(p) for p in presets)})
    tpl = tpl.model_copy(
        update={"groups": tuple(g if x.name == "skills" else x for x in tpl.groups)}
    )
    return pack.model_copy(update={"templates": (tpl, *pack.templates[1:])})


DOUBLE = {"target": "perception_radius", "op": "mul", "value": "2"}


def entry_names(rules: RulesService, pack: RulePack, sheet: JsonValue) -> list[str]:
    full = rules.full_sheet(pack, "person", sheet)
    assert isinstance(full, dict)
    groups = full["groups"]
    assert isinstance(groups, dict)
    entries = groups.get("skills", [])
    assert isinstance(entries, list)
    return [str(e["name"]) for e in entries if isinstance(e, dict)]


def test_preset_appears_only_when_condition_holds(rules: RulesService) -> None:
    pack = with_presets(
        {"name": "triage", "fields": {"level": 1}, "when": 'occupation = "doctor"'},
        {"name": "sail", "fields": {"level": 1}, "when": 'occupation == "sailor"'},
        {"name": "always", "fields": {"level": 1}},
    )
    assert rules.validate_pack(pack) == []
    assert entry_names(rules, pack, BASE) == ["triage", "always"]
    sailor = {**BASE, "fields": {**BASE["fields"], "occupation": "sailor"}}  # type: ignore[dict-item]
    assert entry_names(rules, pack, sailor) == ["sail", "always"]


def test_preset_effects_apply_only_when_active(rules: RulesService) -> None:
    pack = with_presets(
        {"name": "eagle eye", "when": 'occupation != "doctor"', "effects": [DOUBLE]},
    )
    plain = rules.derived_value(pack, "person", BASE, "perception_radius")
    sailor = {**BASE, "fields": {**BASE["fields"], "occupation": "sailor"}}  # type: ignore[dict-item]
    assert rules.derived_value(pack, "person", sailor, "perception_radius") == plain * 2


def test_presets_come_before_own_entries_and_dont_count(rules: RulesService) -> None:
    pack = with_presets({"name": "fixed", "fields": {"level": 1}})
    own: dict[str, JsonValue] = {
        **BASE,
        "groups": {"skills": [{"name": "mine", "fields": {"level": 2}}]},
    }
    assert entry_names(rules, pack, own) == ["fixed", "mine"]
    assert rules.validate_sheet(pack, "person", rules.init_sheet(pack, "person", own)) == []


def test_preset_condition_may_only_use_fields(rules: RulesService) -> None:
    pack = with_presets({"name": "p", "when": "perception_radius > 3"})
    codes = {p.code for p in rules.validate_pack(pack)}
    assert codes == {"formula.unknown_name"}


def test_preset_entries_are_checked(rules: RulesService) -> None:
    pack = with_presets(
        {"name": "", "fields": {"nope": 1}},
        {"name": "x", "effects": [{"target": "nope", "op": "add", "value": "1"}]},
    )
    codes = {p.code for p in rules.validate_pack(pack)}
    assert codes == {"sheet.required", "sheet.unknown_field", "sheet.effect_target"}


def test_condition_error_means_inactive(rules: RulesService) -> None:
    pack = with_presets({"name": "p", "when": "str > 10"})
    no_str: dict[str, JsonValue] = {"name": "X", "fields": {"appearance": "a"}}
    assert entry_names(rules, pack, no_str) == []
