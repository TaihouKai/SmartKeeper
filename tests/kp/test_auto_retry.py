"""KP 出错（模型报错、裁定重试用尽、反馈写不出来）：不停下来等人，过一会儿自动重试，间隔逐渐拉长。"""

from __future__ import annotations

import pytest

from smartkeeper.contracts import LLMError
from smartkeeper.llm import FakeCall
from tests.kp.harness import new_game


def broken(call: FakeCall) -> str:
    raise LLMError("llm.down", call.purpose)


def run_scheduled(g) -> None:  # type: ignore[no-untyped-def]
    todo, g.scheduled[:] = list(g.scheduled), []
    for _delay, fn in todo:
        fn()


def test_a_failed_adjudication_is_retried_until_it_goes_out() -> None:
    g = new_game(2)
    adjudicate = g.llm.handlers["adjudicate"]
    g.llm.on("adjudicate", broken)
    g.play_round()
    assert g.engine.round(g.game_id, 1).status == "review"
    assert [d for d, _ in g.scheduled] == [60]
    run_scheduled(g)  # 模型还没好：再排一次，间隔拉长
    assert [d for d, _ in g.scheduled] == [300]
    g.llm.on("adjudicate", adjudicate)
    run_scheduled(g)
    assert g.engine.round(g.game_id, 1).status == "published"
    assert g.scheduled == []


def test_only_the_feedback_is_rewritten_when_the_adjudication_already_exists() -> None:
    g = new_game(1)
    feedback = g.llm.handlers["feedback"]
    g.llm.on("feedback", broken)
    g.play_round()
    assert g.engine.round(g.game_id, 1).status == "review"
    adjudications = len(g.llm.by_purpose("adjudicate"))
    g.llm.on("feedback", feedback)
    run_scheduled(g)
    assert g.engine.round(g.game_id, 1).status == "published"
    assert len(g.llm.by_purpose("adjudicate")) == adjudications  # 没有重新裁定


def test_after_a_few_retries_the_round_stops_and_waits_until_resumed() -> None:
    """自动重试三次（1、5、15 分钟）还不行就停下：游戏等着，管理员修好代码后点“重跑”接着跑。"""
    g = new_game(1)
    adjudicate = g.llm.handlers["adjudicate"]
    g.llm.on("adjudicate", broken)
    stopped: list[int] = []
    g.kp._on_review = lambda gid, n: stopped.append(n)  # type: ignore[attr-defined]
    g.play_round()
    gaps: list[float] = []
    for _ in range(5):
        gaps += [d for d, _ in g.scheduled]
        run_scheduled(g)
    assert gaps == [60, 300, 900]
    assert g.engine.round(g.game_id, 1).status == "review" and stopped == [1]
    g.llm.on("adjudicate", adjudicate)  # 代码修好了
    g.kp.resume(g.game_id)
    assert g.engine.round(g.game_id, 1).status == "published"


def test_a_failed_character_review_is_retried() -> None:
    from tests.engine.harness import sheets_for
    from tests.fixtures import load_pack

    g = new_game(0, start=False)
    review = g.llm.handlers["review_character"]
    g.llm.on("review_character", broken)
    p, _ = g.engine.add_player(g.game_id, "迟到的人")
    g.engine.assign_identity(p.id)
    g.engine.submit_character(p.id, sheets_for(load_pack("single"), 0))
    with pytest.raises(LLMError):
        g.kp.review_character(p.id)
    assert g.engine.character_status(p.id) == "submitted"
    assert [d for d, _ in g.scheduled] == [60]
    g.llm.on("review_character", review)
    run_scheduled(g)
    assert g.engine.character_status(p.id) == "approved"
