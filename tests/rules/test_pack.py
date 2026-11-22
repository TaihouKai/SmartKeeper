import json

import pytest
import sqlalchemy as sa
from pydantic import JsonValue

from smartkeeper.contracts import DerivedDef, RulePack, ValidationFailed
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
    assert rules.validate_formula(pack, "person", "self.level * 2", in_entry="skills") == []
    assert rules.validate_formula(pack, "person", "self.level * 2") != []


def test_derived_cycle_rejected(rules: RulesService) -> None:
    pack = load_pack("single")
    tpl = pack.templates[0]
    derived = (*tpl.derived, DerivedDef(name="loop", formula="loop + 1"))
    pack = pack.model_copy(update={"templates": (tpl.model_copy(update={"derived": derived}),)})
    assert any(p.code == "formula.cycle" for p in rules.validate_pack(pack))


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


def test_add_before_mul(rules: RulesService) -> None:
    pack = load_pack("single")
    sheet: dict[str, JsonValue] = {
        **BASE,
        "statuses": [
            {
                "tag": "focused",
                "modifier": {"target": "perception_radius", "op": "mul", "value": "2"},
            },
            {
                "tag": "lantern",
                "modifier": {"target": "perception_radius", "op": "add", "value": "10"},
            },
        ],
    }
    assert rules.derived_value(pack, "person", sheet, "perception_radius") == (90 + 10) * 2


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
    assert store.list_packs()[0].versions == ()


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
