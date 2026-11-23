import pytest
from hypothesis import given
from hypothesis import strategies as st

from smartkeeper.contracts import ValidationFailed
from smartkeeper.dice import DiceRoller, SeededRandomSource


@given(count=st.integers(0, 20), sides=st.integers(1, 100), seed=st.integers(0, 2**32))
def test_faces_in_range(count: int, sides: int, seed: int) -> None:
    got = DiceRoller(SeededRandomSource(seed)).faces(count, sides)
    assert len(got) == count
    assert all(1 <= x <= sides for x in got)


def test_seeded_is_reproducible() -> None:
    a = DiceRoller(SeededRandomSource(42)).faces(10, 10)
    b = DiceRoller(SeededRandomSource(42)).faces(10, 10)
    assert a == b


@pytest.mark.parametrize(("count", "sides"), [(-1, 6), (1001, 6), (1, 0), (1, 100001)])
def test_out_of_range(count: int, sides: int) -> None:
    with pytest.raises(ValidationFailed):
        DiceRoller(SeededRandomSource(1)).faces(count, sides)
