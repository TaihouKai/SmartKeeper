"""测试用的假 LLM：按调用用途交给一个处理函数，或者按顺序弹出预置的响应。不联网，不搜索。"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import JsonValue

from smartkeeper.contracts import LLMError, LLMResult, Message


@dataclass(frozen=True)
class FakeCall:
    purpose: str
    model: str
    system: str
    messages: list[Message]
    allow_search: bool
    game_id: str | None

    @property
    def prompt(self) -> str:
        """system 加全部消息的文字，便于断言 prompt 里有什么。"""
        parts = [self.system]
        for m in self.messages:
            c = m.get("content")
            parts.append(c if isinstance(c, str) else str(c))
        return "\n".join(parts)


type Handler = Callable[[FakeCall], str]


@dataclass
class FakeLLM:
    handlers: dict[str, Handler] = field(default_factory=dict[str, Handler])
    queue: dict[str, list[str]] = field(default_factory=dict[str, list[str]])
    calls: list[FakeCall] = field(default_factory=list[FakeCall])
    supports_search: bool = False
    provider: str = "fake"
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def on(self, purpose: str, handler: Handler) -> None:
        self.handlers[purpose] = handler

    def push(self, purpose: str, *responses: str) -> None:
        self.queue.setdefault(purpose, []).extend(responses)

    def by_purpose(self, purpose: str) -> list[FakeCall]:
        return [c for c in self.calls if c.purpose == purpose]

    def complete(
        self,
        *,
        purpose: str,
        model: str,
        system: str,
        messages: list[Message],
        json_schema: dict[str, JsonValue] | None = None,
        allow_search: bool = False,
        game_id: str | None = None,
    ) -> LLMResult:
        del json_schema
        call = FakeCall(purpose, model, system, [dict(m) for m in messages], allow_search, game_id)
        with self._lock:
            self.calls.append(call)
            q = self.queue.get(purpose)
            text = q.pop(0) if q else None
        if text is None:
            handler = self.handlers.get(purpose)
            if handler is None:
                raise LLMError("llm.fake_unhandled", purpose)
            text = handler(call)
        return LLMResult(text=text, model=model or "fake")
