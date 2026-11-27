"""OpenAI Responses API 的实现。联网搜索用 OpenAI 自带的 web_search 工具。

provider="openai"：OpenAI 官方，默认允许联网。
provider="openai_compat" 且配置了开启搜索：同一套请求发到兼容服务的地址（那个服务要实现 Responses API 和 web_search）。
"""

from __future__ import annotations

import time
from typing import Any, cast

import openai
from openai.types.responses import Response
from pydantic import JsonValue

from smartkeeper.contracts import LLMError, LLMResult, Message, SearchRecord

WEB_SEARCH_TOOL: dict[str, Any] = {"type": "web_search"}


def _cached(usage: object) -> int:
    details = getattr(usage, "input_tokens_details", None)
    return int(getattr(details, "cached_tokens", 0) or 0)


class OpenAIResponsesLLM:
    def __init__(
        self,
        client: openai.OpenAI | None = None,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        search: bool = True,
        provider: str = "openai",
        max_tokens: int = 32000,
    ) -> None:
        self._client = client or openai.OpenAI(base_url=base_url, api_key=api_key)
        self.supports_search = search
        self.provider = provider
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
        del purpose, json_schema  # JSON 一律在本地校验，不依赖结构化输出
        t0 = time.monotonic()
        kwargs: dict[str, Any] = {
            "model": model,
            "instructions": system,
            "input": [{"role": m["role"], "content": m["content"]} for m in messages],
            "max_output_tokens": self._max_tokens,
        }
        if allow_search and self.supports_search:
            kwargs["tools"] = [WEB_SEARCH_TOOL]
        if game_id:
            # 同一局的调用落在同一份提示缓存上（开头是同样的规则书和剧本）
            kwargs["prompt_cache_key"] = f"smartkeeper-{game_id}"
        try:
            resp = cast(Response, self._client.responses.create(**kwargs))
        except openai.APIConnectionError as e:
            raise LLMError("llm.connection", str(e)) from e
        except openai.RateLimitError as e:
            raise LLMError("llm.rate_limited", str(e)) from e
        except openai.AuthenticationError as e:
            raise LLMError("llm.auth", str(e)) from e
        except openai.APIStatusError as e:
            raise LLMError("llm.api_error", f"{e.status_code} {e.message}") from e
        searches: list[SearchRecord] = []
        for item in resp.output or []:
            if getattr(item, "type", None) != "web_search_call":
                continue
            action = cast(Any, getattr(item, "action", None))
            if action is not None and getattr(action, "type", None) == "search":
                sources = cast(list[Any], getattr(action, "sources", None) or [])
                urls = tuple(str(src.url) for src in sources)
                query = str(getattr(action, "query", "") or "")
                searches.append(SearchRecord(query=query, urls=urls))
        text = resp.output_text or ""
        reason = resp.incomplete_details.reason if resp.incomplete_details else None
        if resp.status == "incomplete" and not text.strip():
            # 推理或搜索用完了输出上限，没有正文：当成调用失败，而不是“没有 JSON”
            raise LLMError("llm.output_exhausted", f"incomplete: {reason}")
        usage = resp.usage
        return LLMResult(
            text=text,
            model=resp.model,
            input_tokens=usage.input_tokens if usage else 0,
            output_tokens=usage.output_tokens if usage else 0,
            cached_input_tokens=_cached(usage),
            stop_reason=reason or resp.status,
            duration_ms=int((time.monotonic() - t0) * 1000),
            searches=tuple(searches),
        )
