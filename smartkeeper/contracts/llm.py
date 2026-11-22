"""LLM 调用与记事条目的数据类型和接口。"""

from __future__ import annotations

from typing import Protocol

from pydantic import JsonValue

from smartkeeper.contracts.base import Frozen


class SearchRecord(Frozen):
    query: str
    urls: tuple[str, ...] = ()


class LLMResult(Frozen):
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    searches: tuple[SearchRecord, ...] = ()
    stop_reason: str | None = None
    duration_ms: int = 0
    call_id: int | None = None  # llm_call 记录的 id


class LLMError(Exception):
    """调用失败（网络、鉴权、拒答等），不含校验失败。"""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


type Message = dict[str, JsonValue]


class LLMClient(Protocol):
    supports_search: bool

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
        """一次调用。json_schema 只作为提示写进请求，结果一律由调用方在本地校验。"""
        ...


class LLMCallRecord(Frozen):
    id: int
    game_id: str | None
    purpose: str
    provider: str
    model: str
    system: str
    messages: list[Message]
    response: str
    searches: tuple[SearchRecord, ...]
    input_tokens: int
    output_tokens: int
    duration_ms: int
    valid: bool | None
    error: str | None
    created_at: str


class LLMCallLog(Protocol):
    def mark(self, call_id: int, valid: bool) -> None: ...

    def list(self, game_id: str | None = None, limit: int = 200) -> list[LLMCallRecord]: ...


class MemoryEntry(Frozen):
    game_id: str
    round_no: int
    entities: tuple[str, ...]
    features: tuple[str, ...]
    text: str
    source_seq: int


class MemoryStore(Protocol):
    def add(self, entries: list[MemoryEntry]) -> None: ...

    def recall(
        self,
        game_id: str,
        entity_ids: list[str],
        actor_ids: list[str],
        feature_ids: list[str],
    ) -> list[MemoryEntry]:
        """同时标了其中任意两个实体的条目，以及标了某个行动者本人和某个相关地物的条目。"""
        ...

    def all(self, game_id: str) -> list[MemoryEntry]: ...

    def clear(self, game_id: str) -> None: ...
