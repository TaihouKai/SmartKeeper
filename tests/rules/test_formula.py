import pytest
from hypothesis import given
from hypothesis import strategies as st

from smartkeeper.rules import FormulaError
from smartkeeper.rules.formula import evaluate, parse  # 模块内部测试可以导入自己的子模块


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
        ("floor(2.7) + ceil(2.1)", 5),
        ("round(2.5) + round(-2.5)", 0),
        ("min(3, 1, 2) + max(4, 9)", 10),
        ("3 > 2", 1),
        ("3 <= 2", 0),
        ("x * 2", 8),
        ('job == "doctor"', 1),
    ],
)
def test_evaluate(text: str, expected: float) -> None:
    assert ev(text, x=4, job="doctor") == expected


@pytest.mark.parametrize(
    "text",
    [
        "__import__('os')",
        "exec(1)",
        "abs(-1)",
        "x ** 2",
        "x % 2",
        "x[0]",
        "lambda: 1",
        "1 if x else 2",
        "x and y",
        "1 < 2 < 3",
        "",
        "1 +",
        "min()",
        "lookup(1, 2)",
        "f'{x}'",
        "x; y",
    ],
)
def test_rejects_outside_whitelist(text: str) -> None:
    with pytest.raises(FormulaError):
        parse(text)


def test_division_by_zero() -> None:
    with pytest.raises(FormulaError):
        ev("1 / 0")


def test_text_in_arithmetic() -> None:
    with pytest.raises(FormulaError):
        ev("job + 1", job="doctor")


@given(st.integers(-1000, 1000), st.integers(-1000, 1000))
def test_arithmetic_matches_python(a: int, b: int) -> None:
    assert ev(f"{abs(a)} - {abs(b)} * 2") == abs(a) - abs(b) * 2
