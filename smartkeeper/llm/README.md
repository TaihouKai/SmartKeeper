# `llm`

`LLMClient` 及其实现。

- 依赖：`contracts`（Anthropic SDK、OpenAI SDK）
- `AnthropicLLM`：Messages API，流式请求；`allow_search` 时带 `web_search_20260209` 服务端工具，搜索的查询词和网址进 `LLMResult.searches`；`pause_turn` 自动续上；默认开启服务端拒答回退（`fallbacks="default"`，beta `server-side-fallback-2026-07-01`），可用 `server_fallback=False` 关闭。
- `OpenAICompatLLM`：OpenAI 兼容接口，`supports_search=False`。
- `FakeLLM`：测试用，按用途交给处理函数或弹出预置响应；记录全部调用。
- `RecordingLLM` + `SqlLLMCallLog`：把每次调用写进 `llm_call` 表（prompt、响应、搜索记录、token、耗时、是否校验通过）。
- 不依赖提供方的结构化输出，JSON 一律由调用方在本地校验。
- 单独测试：`uv run pytest tests/llm`（不联网）；真模型测试标 `live`。
