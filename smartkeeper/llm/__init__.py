"""`LLMClient` 及其实现：Anthropic SDK、OpenAI Responses API、OpenAI 兼容接口、测试用的 FakeLLM；调用记录；管理员建的几套模型选择。"""

from smartkeeper.llm.anthropic_client import AnthropicLLM
from smartkeeper.llm.fake import FakeCall, FakeLLM
from smartkeeper.llm.openai_compat import OpenAICompatLLM
from smartkeeper.llm.openai_responses import OpenAIResponsesLLM
from smartkeeper.llm.profiles import SqlLLMProfiles
from smartkeeper.llm.recording import RecordingLLM, SqlLLMCallLog
from smartkeeper.llm.recording import metadata as llm_metadata

__all__ = [
    "AnthropicLLM",
    "FakeCall",
    "FakeLLM",
    "OpenAICompatLLM",
    "OpenAIResponsesLLM",
    "RecordingLLM",
    "SqlLLMCallLog",
    "SqlLLMProfiles",
    "llm_metadata",
]
