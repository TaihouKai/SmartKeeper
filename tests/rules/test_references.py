"""公式里的引用：<模板>.x（自己这边的实体）、<模板>.<条目ID>、<模板>.<条目ID>.<列>、target.x。"""

from pydantic import JsonValue

from smartkeeper.contracts import DerivedDef, GroupPreset, RulePack
from smartkeeper.rules import RulesService
from tests.fixtures import load_pack

LEADER: dict[str, JsonValue] = {
    "name": "L",
    "fields": {"looks": "x", "might": 14, "agility": 20, "wits": 8},
    "groups": {"talents": [{"name": "steady", "id": "steady", "fields": {"rank": 2}}]},
}
COMPANION: dict[str, JsonValue] = {
    "name": "C",
    "fields": {"looks": "y", "power": 7, "range_m": 30},
}


def with_derived(pack: RulePack, template: str, *defs: DerivedDef) -> RulePack:
    tpls = tuple(
        t.model_copy(update={"derived": (*t.derived, *defs)}) if t.name == template else t
        for t in pack.templates
    )
    return pack.model_copy(update={"templates": tpls})


def test_partner_fields_and_own_entries(rules: RulesService) -> None:
    pack = with_derived(
        load_pack("multi"),
        "leader",
        DerivedDef(name="bond", formula="companion.power + leader.might"),
        DerivedDef(name="has_steady", formula="leader.steady + leader.nothing_here"),
        DerivedDef(name="steady_rank", formula="leader.steady.rank * 10"),
    )
    # 规则包校验只认得固定条目的 ID；这里引用的是玩家写的条目，直接求值
    peers: dict[str, JsonValue | None] = {"companion": COMPANION}
    got = {d.name: d.value for d in rules.derive(pack, "leader", LEADER, peers)}
    assert got["bond"] == 7 + 14
    assert got["has_steady"] == 1  # 有 steady，没有 nothing_here
    assert got["steady_rank"] == 20
    # 我这边没有这种角色：按 0 算
    alone = {d.name: d.value for d in rules.derive(pack, "leader", LEADER)}
    assert alone["bond"] == 14


def test_ambiguous_partner_is_an_error(rules: RulesService) -> None:
    import pytest

    from smartkeeper.contracts import ValidationFailed

    pack = with_derived(
        load_pack("multi"), "leader", DerivedDef(name="bond", formula="companion.power")
    )
    with pytest.raises(ValidationFailed) as err:
        rules.derive(pack, "leader", LEADER, {"companion": None})
    assert err.value.code == "formula.ambiguous_partner"


def test_cross_entity_cycle_is_found(rules: RulesService) -> None:
    import pytest

    from smartkeeper.contracts import ValidationFailed

    pack = with_derived(load_pack("multi"), "leader", DerivedDef(name="a", formula="companion.b"))
    pack = with_derived(pack, "companion", DerivedDef(name="b", formula="leader.a"))
    with pytest.raises(ValidationFailed) as err:
        rules.derive(pack, "leader", LEADER, {"companion": COMPANION})
    assert err.value.code == "formula.cycle"


def test_reference_names_are_checked(rules: RulesService) -> None:
    pack = load_pack("multi")
    tpl = pack.template("leader")
    assert tpl is not None
    g = tpl.groups[0]
    preset = GroupPreset.model_validate({"name": "grit", "id": "grit", "fields": {"rank": 1}})
    g = g.model_copy(update={"presets": (preset,)})
    pack = pack.model_copy(
        update={
            "templates": tuple(
                t.model_copy(update={"groups": (g,)}) if t.name == "leader" else t
                for t in pack.templates
            )
        }
    )
    ok = ["companion.power", "leader.grit", "leader.grit.rank", "target.might", "leader.template"]
    for name in ok:
        assert rules.validate_formula(pack, "leader", name) == [], name
    for name in ["nobody.power", "companion.nothing", "leader.grit.nope"]:
        assert rules.validate_formula(pack, "leader", name) != [], name


def test_entry_ids_must_be_unique_and_not_clash(rules: RulesService) -> None:
    pack = load_pack("multi")

    def codes(*entries: dict[str, JsonValue]) -> set[str]:
        sheet = rules.init_sheet(pack, "leader", {**LEADER, "groups": {"talents": list(entries)}})
        return {p.code for p in rules.validate_sheet(pack, "leader", sheet)}

    assert codes({"name": "a", "id": "x", "fields": {"rank": 1}}) == set()
    dup = codes(
        {"name": "a", "id": "x", "fields": {"rank": 1}},
        {"name": "b", "id": "x", "fields": {"rank": 1}},
    )
    assert "sheet.duplicate_entry_id" in dup
    assert "sheet.entry_id_clash" in codes({"name": "a", "id": "might", "fields": {"rank": 1}})
    assert "sheet.bad_entry_id" in codes({"name": "a", "id": "9lives", "fields": {"rank": 1}})
