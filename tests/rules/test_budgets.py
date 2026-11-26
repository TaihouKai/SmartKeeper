"""合计上限：字段和各条目的列合计起来，超了报问题；条件不成立时不限；定义写错时规则包校验报出来。"""

from typing import Any

from pydantic import JsonValue

from smartkeeper.contracts import BudgetDef, RulePack
from smartkeeper.rules import RulesService
from tests.fixtures import load_pack


def with_budgets(*budgets: dict[str, Any]) -> RulePack:
    pack = load_pack("single")
    tpl = pack.templates[0]
    tpl = tpl.model_copy(update={"budgets": tuple(BudgetDef.model_validate(b) for b in budgets)})
    # 夹具的例题不按这里的点数建，去掉
    return pack.model_copy(update={"templates": (tpl, *pack.templates[1:]), "samples": ()})


def sheet(occupation: str, str_: int, skills: list[int]) -> JsonValue:
    return {
        "name": "X",
        "fields": {"appearance": "a", "occupation": occupation, "str": str_, "dex": 10, "per": 10},
        "groups": {
            "skills": [{"name": f"s{i}", "fields": {"level": lv}} for i, lv in enumerate(skills)]
        },
    }


POINTS = {
    "name": "points",
    "label": "点数",
    "fields": ["str", "dex", "per"],
    "columns": ["skills.level"],
    "total": '50 + (10 if occupation == "doctor" else 0)',
}


def test_sum_of_fields_and_columns(rules: RulesService) -> None:
    pack = with_budgets(POINTS)
    assert rules.validate_pack(pack) == []
    s = rules.init_sheet(pack, "person", sheet("reporter", 20, [3, 4]))
    [u] = rules.budgets(pack, "person", s)
    assert (u.used, u.total, u.active) == (47, 50, True)
    assert rules.validate_sheet(pack, "person", s) == []


def test_over_the_cap_is_a_problem_and_the_cap_follows_the_sheet(rules: RulesService) -> None:
    pack = with_budgets(POINTS)
    over = rules.init_sheet(pack, "person", sheet("reporter", 30, [3, 4]))
    problems = rules.validate_sheet(pack, "person", over, creation=True)
    assert [(p.code, p.path) for p in problems] == [("sheet.budget_over", "budgets.points")]
    assert problems[0].params["used"] == 57 and problems[0].params["total"] == 50
    # 合计上限只管建角：剧本的 NPC、游戏中的状态不查
    assert rules.validate_sheet(pack, "person", over) == []
    # 医生多 10 点：同样的填写就不超了
    doctor = rules.init_sheet(pack, "person", sheet("doctor", 30, [3, 4]))
    assert rules.validate_sheet(pack, "person", doctor) == []


def test_condition_and_no_cap(rules: RulesService) -> None:
    pack = with_budgets(
        {"name": "only_doctors", "fields": ["str"], "total": "5", "when": 'occupation == "doctor"'},
        {"name": "shown", "fields": ["dex", "per"]},
    )
    s = rules.init_sheet(pack, "person", sheet("reporter", 30, []))
    uses = {u.name: u for u in rules.budgets(pack, "person", s)}
    assert uses["only_doctors"].active is False and uses["only_doctors"].total is None
    assert uses["shown"].used == 20 and uses["shown"].total is None
    assert rules.validate_sheet(pack, "person", s) == []
    doc = rules.init_sheet(pack, "person", sheet("doctor", 30, []))
    assert [p.code for p in rules.validate_sheet(pack, "person", doc, creation=True)] == [
        "sheet.budget_over"
    ]


def test_bad_definitions(rules: RulesService) -> None:
    pack = with_budgets(
        {"name": "a", "fields": ["nope", "appearance"], "total": "1"},
        {"name": "a", "columns": ["skills.nope", "nogroup.level"], "total": "x +"},
        {"name": "b"},
    )
    codes = sorted({p.code for p in rules.validate_pack(pack)})
    assert {
        "pack.budget_field",
        "pack.budget_column",
        "pack.budget_empty",
        "pack.duplicate_name",
    } <= set(codes)
    assert any(c.startswith("formula.") for c in codes)
