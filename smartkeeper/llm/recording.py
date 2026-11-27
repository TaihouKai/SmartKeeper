"""llm_call 表：每次调用的用途、实现与模型、完整 prompt、响应、搜索记录、token、耗时、是否校验通过。"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from pydantic import JsonValue

from smartkeeper.contracts import (
    LLMCallRecord,
    LLMClient,
    LLMError,
    LLMResult,
    Message,
    SearchRecord,
)

metadata = sa.MetaData()

llm_call = sa.Table(
    "llm_call",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("game_id", sa.String, nullable=True, index=True),
    sa.Column("purpose", sa.String, nullable=False),
    sa.Column("provider", sa.String, nullable=False),
    sa.Column("model", sa.String, nullable=False),
    sa.Column("system", sa.Text, nullable=False),
    sa.Column("messages", sa.Text, nullable=False),
    sa.Column("response", sa.Text, nullable=False),
    sa.Column("searches", sa.Text, nullable=False),
    sa.Column("input_tokens", sa.Integer, nullable=False),
    sa.Column("output_tokens", sa.Integer, nullable=False),
    sa.Column("cached_input_tokens", sa.Integer, nullable=False, server_default="0"),
    sa.Column("duration_ms", sa.Integer, nullable=False),
    sa.Column("valid", sa.Boolean, nullable=True),
    sa.Column("error", sa.Text, nullable=True),
    sa.Column("created_at", sa.String, nullable=False),
)


def _record(m: Any) -> LLMCallRecord:
    return LLMCallRecord(
        id=m["id"],
        game_id=m["game_id"],
        purpose=m["purpose"],
        provider=m["provider"],
        model=m["model"],
        system=m["system"],
        messages=json.loads(m["messages"]),
        response=m["response"],
        searches=tuple(SearchRecord.model_validate(s) for s in json.loads(m["searches"])),
        input_tokens=m["input_tokens"],
        output_tokens=m["output_tokens"],
        cached_input_tokens=m["cached_input_tokens"],
        duration_ms=m["duration_ms"],
        valid=m["valid"],
        error=m["error"],
        created_at=m["created_at"],
    )


class SqlLLMCallLog:
    def __init__(self, db: sa.Engine) -> None:
        self._db = db
        self._lock = threading.Lock()
        metadata.create_all(db)

    def insert(self, **values: Any) -> int:
        values.setdefault("created_at", datetime.now(UTC).isoformat())
        with self._lock, self._db.begin() as c:
            res = c.execute(llm_call.insert().values(**values))
            pk = res.inserted_primary_key
            assert pk is not None
            return int(pk[0])

    def mark(self, call_id: int, valid: bool) -> None:
        with self._db.begin() as c:
            c.execute(llm_call.update().where(llm_call.c.id == call_id).values(valid=valid))

    def list(self, game_id: str | None = None, limit: int = 200) -> list[LLMCallRecord]:
        q = sa.select(llm_call).order_by(llm_call.c.id.desc()).limit(limit)
        if game_id is not None:
            q = q.where(llm_call.c.game_id == game_id)
        with self._db.connect() as c:
            rows = c.execute(q).all()
        return [_record(r._mapping) for r in rows]  # pyright: ignore[reportPrivateUsage]


class RecordingLLM:
    """包一层，把每次调用写进 llm_call。"""

    def __init__(self, inner: LLMClient, log: SqlLLMCallLog) -> None:
        self._inner = inner
        self._log = log
        self.supports_search = inner.supports_search
        self.provider = str(getattr(inner, "provider", type(inner).__name__))

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
        base: dict[str, Any] = {
            "game_id": game_id,
            "purpose": purpose,
            "provider": self.provider,
            "model": model,
            "system": system,
            "messages": json.dumps(messages, ensure_ascii=False),
        }
        try:
            res = self._inner.complete(
                purpose=purpose,
                model=model,
                system=system,
                messages=messages,
                json_schema=json_schema,
                allow_search=allow_search and self.supports_search,
                game_id=game_id,
            )
        except LLMError as e:
            self._log.insert(
                **base,
                response="",
                searches="[]",
                input_tokens=0,
                output_tokens=0,
                cached_input_tokens=0,
                duration_ms=0,
                valid=False,
                error=str(e),
            )
            raise
        call_id = self._log.insert(
            **{**base, "model": res.model or model},
            response=res.text,
            searches=json.dumps([s.model_dump() for s in res.searches], ensure_ascii=False),
            input_tokens=res.input_tokens,
            output_tokens=res.output_tokens,
            cached_input_tokens=res.cached_input_tokens,
            duration_ms=res.duration_ms,
            valid=None,
            error=None,
        )
        return res.model_copy(update={"call_id": call_id})
