import pytest
from hypothesis import given
from hypothesis import strategies as st

from smartkeeper.lang import FormulaError, desugar, evaluate, parse, to_text


def ev(text: str, **names: float | str) -> float | str:
    def resolve(n: str) -> float | str:
        return names[n]

    def lookup(t: str, k: float | str) -> float:
        raise AssertionError

    return evaluate(parse(text), resolve, lookup)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1 + 2 * 3", 7),
        ("(1 + 2) * 3", 9),
        ("-2 * -3", 6),
        ("10 / 4", 2.5),
        ("7 // 2", 3),
        ("-1 % 3", 2),
        ("2 ** 10", 1024),
        ("floor(2.7) + ceil(2.1)", 5),
        ("round(2.5) + round(-2.5)", 0),
        ("min(3, 1, 2) + max(4, 9)", 10),
        ("3 > 2", 1),
        ("3 <= 2", 0),
        ("1 < x < 5", 1),
        ("1 < x < 3", 0),
        ("x * 2", 8),
        ('job == "doctor"', 1),
        ("job == 'doctor'", 1),
        ('2 if job == "doctor" else 3', 2),
        ("x > 3 and not x > 5", 1),
        ("0 or x", 1),
        ("True + False", 1),
        ("  x  ", 4),
    ],
)
def test_evaluate(text: str, expected: float) -> None:
    assert ev(text, x=4, job="doctor") == expected


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("__import__('os')", "formula.unknown_function"),
        ("exec(1)", "formula.unknown_function"),
        ("x.y(1)", "formula.unknown_function"),
        ("x[0]", "formula.unsupported"),
        ("lambda: 1", "formula.unsupported"),
        ("[1, 2]", "formula.unsupported"),
        ("x in y", "formula.unsupported"),
        ("f'{x}'", "formula.unsupported"),
        ("(1).real", "formula.unsupported"),
        ("min(*x)", "formula.unknown_function"),
        ("max(x, key=1)", "formula.unknown_function"),
        ("", "formula.empty"),
        ("1 +", "formula.syntax"),
        ("(1 + 2", "formula.unclosed"),
        ("1 + 2)", "formula.unmatched"),
        ('"abc', "formula.unclosed_string"),
        ('cls = "warrior"', "formula.single_equals"),
        ("x; y", "formula.syntax"),
        ("min()", "formula.arity"),
        ("lookup(1, 2)", "formula.lookup_table_name"),
        ("count(1)", "formula.list_ref"),
        ("if(x, 1, 2)", "formula.if_call"),
    ],
)
def test_rejects_outside_whitelist(text: str, code: str) -> None:
    with pytest.raises(FormulaError) as err:
        parse(text)
    assert err.value.code == code


def test_if_is_lazy() -> None:
    assert ev("5 if 1 else 1 / 0") == 5
    assert ev("0 and 1 / 0") == 0


def test_division_by_zero() -> None:
    with pytest.raises(FormulaError):
        ev("1 / 0")


def test_text_in_arithmetic() -> None:
    with pytest.raises(FormulaError):
        ev("job + 1", job="doctor")


@given(st.integers(-1000, 1000), st.integers(-1000, 1000))
def test_arithmetic_matches_python(a: int, b: int) -> None:
    assert ev(f"{abs(a)} - {abs(b)} * 2") == abs(a) - abs(b) * 2


@pytest.mark.parametrize(
    ("text", "out"),
    [
        ("3d6 + 2", "dice(3, 6) + 2"),
        ("d20 * d%", "dice(1, 20) * dice(1, 100)"),
        ("2d(str + 1d4)", "dice(2, (str + dice(1, 4)))"),
        ("1d str", "dice(1, str)"),
        ("1dthis.level", "dice(1, this.level)"),
        ("1d lookup(t, x)", "dice(1, lookup(t, x))"),
        ('"3d6" # 1d6', '"3d6" # 1d6'),
        ("x2d6 + a.d6 + d6x", "x2d6 + a.d6 + d6x"),
    ],
)
def test_desugar(text: str, out: str) -> None:
    assert desugar(text) == out


@pytest.mark.parametrize(
    "text",
    [
        "3d6 + 2",
        "dice(level, luck)",
        '"a\\"b" == x',
        "1 if a > 2 else -3",
        "a and b or not c",
        "1 < x <= 3",
        "-x * 2 ** 3 % 4 // 5",
        "count(hero.skills.rank, 3) + sum(skills.cost)",
    ],
)
def test_to_text_round_trips(text: str) -> None:
    node = parse(text)
    assert parse(to_text(node)) == node
