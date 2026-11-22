from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
import sqlalchemy as sa

from smartkeeper.contracts import LLMError
from smartkeeper.llm import AnthropicLLM, FakeLLM, RecordingLLM, SqlLLMCallLog


class _Stream:
    def __init__(self, msg: Any) -> None:
        self.msg = msg

    def __enter__(self) -> _Stream:
        return self

    def __exit__(self, *a: object) -> None:
        return None

    def get_final_message(self) -> Any:
        return self.msg


class StubAnthropic:
    """模仿 SDK 的 client.beta.messages.stream(...)，按顺序返回预置的消息。"""

    def __init__(self, messages: list[Any]) -> None:
        self.sent: list[dict[str, Any]] = []
        outer = self

        class _Messages:
            def stream(self, **kw: Any) -> _Stream:
                outer.sent.append(kw)
                return _Stream(messages.pop(0))

        self.beta = SimpleNamespace(messages=_Messages())


def msg(content: list[Any], stop: str = "end_turn") -> Any:
    return SimpleNamespace(
        content=content,
        stop_reason=stop,
        model="claude-opus-5-5",
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    )


def test_anthropic_text_search_and_pause_turn() -> None:
    first = msg(
        [
            SimpleNamespace(type="server_tool_use", id="s1", input={"query": "setting wiki"}),
            SimpleNamespace(
                type="web_search_tool_result",
                tool_use_id="s1",
                content=[SimpleNamespace(url="https://example.org/a")],
            ),
            SimpleNamespace(type="text", text="part one "),
        ],
        stop="pause_turn",
    )
    second = msg([SimpleNamespace(type="text", text="part two")])
    stub = StubAnthropic([first, second])
    llm = AnthropicLLM(stub, max_tokens=1000)  # type: ignore[arg-type]
    res = llm.complete(
        purpose="x",
        model="claude-opus-5-5",
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        allow_search=True,
    )
    assert res.text == "part one part two"
    assert res.searches[0].query == "setting wiki"
    assert res.searches[0].urls == ("https://example.org/a",)
    assert (res.input_tokens, res.output_tokens) == (20, 10)
    assert stub.sent[0]["tools"][0]["type"] == "web_search_20260209"
    assert stub.sent[0]["fallbacks"] == "default"
    assert len(stub.sent[1]["messages"]) == 2  # 暂停的那一段被接回去继续


def test_anthropic_no_search_tool_when_disallowed_and_refusal() -> None:
    stub = StubAnthropic([msg([], stop="refusal")])
    llm = AnthropicLLM(stub)  # type: ignore[arg-type]
    with pytest.raises(LLMError):
        llm.complete(
            purpose="x", model="m", system="s", messages=[{"role": "user", "content": "x"}]
        )
    assert "tools" not in stub.sent[0]


def test_recording_writes_llm_call() -> None:
    log = SqlLLMCallLog(sa.create_engine("sqlite://"))
    fake = FakeLLM()
    fake.push("chat", "hello")
    rec = RecordingLLM(fake, log)
    res = rec.complete(
        purpose="chat",
        model="m",
        system="S",
        messages=[{"role": "user", "content": "q"}],
        game_id="g1",
    )
    assert res.call_id is not None
    log.mark(res.call_id, True)
    (row,) = log.list("g1")
    assert (row.purpose, row.response, row.valid, row.system) == ("chat", "hello", True, "S")
    with pytest.raises(LLMError):
        rec.complete(purpose="nothing", model="m", system="S", messages=[], game_id="g1")
    assert log.list("g1")[0].error is not None


def test_fake_never_searches() -> None:
    fake = FakeLLM()
    assert fake.supports_search is False
