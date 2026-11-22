import pytest
from hypothesis import given
from hypothesis import strategies as st

from smartkeeper.dice import DiceRoller, SeededRandomSource, bounds, parse, validate


@pytest.mark.parametrize(
    ("expr", "lo", "hi"),
    [("1d100", 1, 100), ("d100", 1, 100), ("3d6+2", 5, 20), ("2d6-1d4+1", -1, 12), ("7", 7, 7)],
)
def test_bounds(expr: str, lo: int, hi: int) -> None:
    assert bounds(expr) == (lo, hi)


@pytest.mark.parametrize("expr", ["", "d", "1d0", "2d6+", "3x6", "1d6 1d6", "0d6", "1d6*2"])
def test_invalid(expr: str) -> None:
    assert validate(expr)
    with pytest.raises(ValueError):
        parse(expr)


@given(
    count=st.integers(1, 20),
    sides=st.integers(1, 100),
    k=st.integers(-50, 50),
    seed=st.integers(0, 2**32),
)
def test_roll_in_range(count: int, sides: int, k: int, seed: int) -> None:
    expr = f"{count}d{sides}{k:+d}"
    lo, hi = bounds(expr)
    r = DiceRoller(SeededRandomSource(seed)).roll(expr)
    assert lo <= r.total <= hi
    assert len(r.rolls) == count
    assert all(1 <= f <= sides for f in r.rolls)


def test_seeded_is_reproducible() -> None:
    a = DiceRoller(SeededRandomSource(42)).roll("10d10")
    b = DiceRoller(SeededRandomSource(42)).roll("10d10")
    assert a == b
