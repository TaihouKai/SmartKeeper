"""三类模型的装配：Claude 和 ChatGPT 默认联网，OpenAI 兼容接口由配置决定。"""


def test_provider_kinds_and_default_search() -> None:
    from smartkeeper.web.app import Settings, make_llm

    s = Settings(official_openai_key="sk-test", openai_base_url="http://x/v1", openai_api_key="k")
    assert make_llm("anthropic", s).supports_search
    assert make_llm("openai", s).supports_search
    assert not make_llm("openai_compat", s).supports_search
    on = Settings(openai_base_url="http://x/v1", openai_api_key="k", openai_compat_search=True)
    assert make_llm("openai_compat", on).supports_search
