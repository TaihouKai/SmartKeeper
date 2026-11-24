"""公式里的掷骰与新增函数。"""

import pytest

from smartkeeper.contracts import ValidationFailed
from smartkeeper.lang import FormulaError, evaluate, has_dice, parse
from smartkeeper.rules import RulesService
from tests.fixtures import FakeDice, load_pack


def ev(text: str, faces: list[int] | None = None, **names: float | str) -> float | str:
    dice = FakeDice(faces)

    def lookup(t: str, k: float | str) -> float:
        raise AssertionError

    return evaluate(parse(text), lambda n: names[n], lookup, dice.faces)


@pytest.mark.parametrize(
    ("text", "faces", "expected"),
    [
        ("3d6", [1, 2, 3], 6),
        ("3D6+2", [1, 2, 3], 8),
        ("d20", [7], 7),
        ("d%", [42], 42),
        ("2d6*5", [3, 4], 35),
        ("-1d4", [3], -3),
        ("1dstr", [5], 5),
        ("2d str", [5, 6], 11),
        ("dice(lv, luck)", [2, 2, 2], 6),
        ("dice(lv, luck) * 2", [1, 1, 1], 6),
        ("2d(str + 1)", [1, 1], 2),
        ("1d6 + 1d4", [6, 4], 10),
        ("highest(4, 6, 3)", [1, 5, 3, 6], 14),
        ("lowest(2, 20, 1)", [15, 4], 4),
        ("0d6", [], 0),
    ],
)
def test_dice(text: str, faces: list[int], expected: float) -> None:
    assert ev(text, faces, str=10, lv=3, luck=8) == expected


def test_dice_sides_and_count_come_from_names() -> None:
    dice = FakeDice()
    evaluate(
        parse("dice(lv, luck)"), {"lv": 3.0, "luck": 8.0}.__getitem__, lambda t, k: 0, dice.faces
    )
    assert dice.calls == [(3, 8)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("abs(-3)", 3),
        ("trunc(-2.7)", -2),
        ("sign(-5) + sign(0) + sign(2)", 0),
        ("sqrt(16)", 4),
        ("pow(2, 10)", 1024),
        ("mod(7, 3) + mod(-1, 3)", 3),
        ("clamp(15, 0, 10) + clamp(-3, 0, 10)", 10),
        ('("big" if x > 3 else "small") == "big"', 1),
        ("(1 and x > 3) + (0 or 0) + (not 0)", 2),
    ],
)
def test_functions(text: str, expected: float) -> None:
    assert ev(text, x=4) == expected


def test_dice_not_allowed_without_faces() -> None:
    with pytest.raises(FormulaError) as e:
        evaluate(parse("1d6"), lambda n: 0.0, lambda t, k: 0.0)
    assert e.value.code == "formula.dice_not_allowed"


@pytest.mark.parametrize("text", ["1d0", "2000d6", "dice(0 - 1, 6)"])
def test_dice_range(text: str) -> None:
    with pytest.raises(FormulaError):
        ev(text, [1] * 10)


def test_has_dice() -> None:
    assert has_dice(parse("1 + max(2d6, 3)"))
    assert has_dice(parse("highest(4, 6, 3)"))
    assert not has_dice(parse("dex * 2 + floor(str / 2)"))


def test_dice_rejected_in_derived_values(rules: RulesService) -> None:
    pack = load_pack("single")
    codes = [p.code for p in rules.validate_formula(pack, "person", "str + 1d6")]
    assert codes == ["formula.dice_not_allowed"]
    assert rules.validate_formula(pack, None, "1d str + 1d6", scope="dice") == []


def test_glued_names_get_a_hint(rules: RulesService) -> None:
    pack = load_pack("single")
    problems = rules.validate_formula(pack, None, "strdper", scope="dice")
    assert [p.code for p in problems] == ["formula.dice_needs_space"]
    assert problems[0].params["fixed"] == "dice(str, per)"


def test_check_dice_may_use_sheet_fields(rules: RulesService) -> None:
    pack = load_pack("single")
    check = pack.checks[0]
    pack = pack.model_copy(
        update={"checks": (check.model_copy(update={"dice": "1d str"}), *pack.checks[1:])}
    )
    assert rules.validate_pack(pack) == []
    sheet = rules.init_sheet(pack, "person", pack.samples[0].sheet)
    dice = FakeDice([4])
    res = rules.roll(pack, "1d str", dice.faces, "person", sheet)
    assert res.total == 4 and res.rolls == (4,)
    assert dice.calls[0][1] == pack.samples[0].sheet["fields"]["str"]  # type: ignore[index]


def test_roll_reports_formula_errors(rules: RulesService) -> None:
    with pytest.raises(ValidationFailed):
        rules.roll(load_pack("single"), "1d6 +", FakeDice().faces)
