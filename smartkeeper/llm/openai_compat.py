"""OpenAI 兼容接口的实现。背后的服务不一定带搜索，所以这里不联网。"""

from __future__ import annotations

import time
from typing import Any, cast

import openai
from pydantic import JsonValue

from smartkeeper.contracts import LLMError, LLMResult, Message


class OpenAICompatLLM:
    supports_search = False
    provider = "openai_compat"

    def __init__(self, *, base_url: str, api_key: str, max_tokens: int = 32000) -> None:
        self._client = openai.OpenAI(base_url=base_url, api_key=api_key)
        self._max_tokens = max_tokens

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
        del purpose, json_schema, allow_search, game_id
        t0 = time.monotonic()
        msgs: list[dict[str, Any]] = [{"role": "system", "content": system}]
        msgs += [dict(m) for m in messages]
        try:
            resp = self._client.chat.completions.create(
                model=model, messages=cast(Any, msgs), max_tokens=self._max_tokens
            )
        except openai.APIConnectionError as e:
            raise LLMError("llm.connection", str(e)) from e
        except openai.RateLimitError as e:
            raise LLMError("llm.rate_limited", str(e)) from e
        except openai.AuthenticationError as e:
            raise LLMError("llm.auth", str(e)) from e
        except openai.APIStatusError as e:
            raise LLMError("llm.api_error", f"{e.status_code} {e.message}") from e
        choice = resp.choices[0]
        if choice.finish_reason == "length" and not (choice.message.content or "").strip():
            # 推理用完了输出上限，没有正文：当成调用失败，而不是“没有 JSON”
            raise LLMError(
                "llm.output_exhausted", f"no content within max_tokens={self._max_tokens}"
            )
        usage = resp.usage
        return LLMResult(
            text=choice.message.content or "",
            model=resp.model,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            stop_reason=choice.finish_reason,
            duration_ms=int((time.monotonic() - t0) * 1000),
        )
