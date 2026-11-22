"""Anthropic SDK 实现。联网搜索用模型提供方自带的 web_search 服务端工具。"""

from __future__ import annotations

import time
from typing import Any, cast

import anthropic
from pydantic import JsonValue

from smartkeeper.contracts import LLMError, LLMResult, Message, SearchRecord

WEB_SEARCH_TOOL: dict[str, Any] = {
    "type": "web_search_20260209",
    "name": "web_search",
    "max_uses": 5,
}
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_PAUSE_RESUMES = 4


class AnthropicLLM:
    """Messages API。流式请求以免长输出超时；拒答时由服务端回退到其他模型（fallbacks="default"）。"""

    supports_search = True
    provider = "anthropic"

    def __init__(
        self,
        client: anthropic.Anthropic | None = None,
        *,
        max_tokens: int = 32000,
        effort: str | None = None,
        server_fallback: bool = True,
    ) -> None:
        self._client = client or anthropic.Anthropic()
        self._max_tokens = max_tokens
        self._effort = effort
        self._fallback = server_fallback

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
        del purpose, game_id, json_schema  # JSON 一律在本地校验，不依赖结构化输出
        t0 = time.monotonic()
        convo: list[dict[str, Any]] = [dict(m) for m in messages]
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": self._max_tokens,
            "system": system,
        }
        if allow_search:
            kwargs["tools"] = [WEB_SEARCH_TOOL]
        if self._effort:
            kwargs["output_config"] = {"effort": self._effort}
        if self._fallback:
            kwargs["betas"] = [FALLBACK_BETA]
            kwargs["fallbacks"] = "default"
        texts: list[str] = []
        searches: list[SearchRecord] = []
        in_tok = out_tok = 0
        stop: str | None = None
        served_by = model
        try:
            for _ in range(MAX_PAUSE_RESUMES + 1):
                with self._client.beta.messages.stream(
                    messages=cast(Any, convo), **kwargs
                ) as stream:
                    msg = stream.get_final_message()
                in_tok += msg.usage.input_tokens
                out_tok += msg.usage.output_tokens
                stop = msg.stop_reason
                served_by = msg.model
                queries: dict[str, str] = {}
                for block in msg.content:
                    btype = getattr(block, "type", "")
                    if btype == "text":
                        texts.append(cast(Any, block).text)
                    elif btype == "server_tool_use":
                        b = cast(Any, block)
                        raw_in: Any = b.input
                        inp = cast(dict[str, Any], raw_in) if isinstance(raw_in, dict) else {}
                        queries[str(b.id)] = str(inp.get("query", ""))
                    elif btype == "web_search_tool_result":
                        b = cast(Any, block)
                        content: Any = b.content
                        results = cast(list[Any], content) if isinstance(content, list) else []
                        urls = tuple(str(getattr(r, "url", "")) for r in results)
                        searches.append(
                            SearchRecord(query=queries.get(b.tool_use_id, ""), urls=urls)
                        )
                if stop == "pause_turn":
                    # 服务端工具的长回合：把这一段原样接回去继续
                    convo.append({"role": "assistant", "content": msg.content})
                    continue
                break
        except anthropic.APIConnectionError as e:
            raise LLMError("llm.connection", str(e)) from e
        except anthropic.RateLimitError as e:
            raise LLMError("llm.rate_limited", str(e)) from e
        except anthropic.AuthenticationError as e:
            raise LLMError("llm.auth", str(e)) from e
        except anthropic.APIStatusError as e:
            raise LLMError("llm.api_error", f"{e.status_code} {e.message}") from e
        if stop == "refusal":
            raise LLMError("llm.refusal", "the model declined this request")
        return LLMResult(
            text="".join(texts),
            model=served_by,
            input_tokens=in_tok,
            output_tokens=out_tok,
            searches=tuple(searches),
            stop_reason=stop,
            duration_ms=int((time.monotonic() - t0) * 1000),
        )
