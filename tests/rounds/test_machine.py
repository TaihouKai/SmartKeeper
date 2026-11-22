import itertools
from typing import get_args

import pytest

from smartkeeper.contracts import IllegalState, RoundStatus
from smartkeeper.rounds import TRANSITIONS, RoundStateMachine

STATUSES: tuple[RoundStatus, ...] = get_args(RoundStatus)
ACTIONS = sorted({a for _, a in TRANSITIONS})


@pytest.mark.parametrize(("status", "action"), list(itertools.product(STATUSES, ACTIONS)))
def test_table(status: RoundStatus, action: str) -> None:
    m = RoundStateMachine()
    expected = TRANSITIONS.get((status, action))
    if expected is None:
        with pytest.raises(IllegalState):
            m.transition(status, action)
    else:
        assert m.transition(status, action) == expected


def test_examples() -> None:
    m = RoundStateMachine()
    with pytest.raises(IllegalState):
        m.transition("adjudicating", "declare")  # 裁定中不能提交行动
    with pytest.raises(IllegalState):
        m.transition("published", "publish")  # 不能重复发布
    assert m.allowed("published") == []
