"""每局用哪套模型：局的设置里选了管理员建的哪套（LLMProfile），没选就是服务器配置的默认那套。"""

from __future__ import annotations

import threading
from collections.abc import Callable

from smartkeeper.contracts import LLMClient, LLMProfile, ValidationFailed
from smartkeeper.engine import Engine
from smartkeeper.llm import SqlLLMProfiles

DEFAULT_PROFILE = ""  # GameSettings.llm_profile 空着：服务器配置的那套


class LLMRouter:
    def __init__(
        self,
        engine: Engine,
        profiles: SqlLLMProfiles,
        default: LLMProfile,
        default_clients: tuple[LLMClient, LLMClient],
        providers: list[str],
        make_client: Callable[[str], LLMClient],
    ) -> None:
        """default：服务器配置的那套（id 为空）；default_clients 是它的裁定和其余调用的实现。
        providers：服务器上配好了密钥、可以在 profile 里选的实现。make_client 按名字建一个（建过就复用）。"""
        self._engine = engine
        self.profiles = profiles
        self.default = default
        self._default_clients = default_clients
        self.providers = providers
        self._make = make_client
        self._clients: dict[str, LLMClient] = {}
        self._lock = threading.Lock()

    def _client(self, provider: str) -> LLMClient:
        with self._lock:
            if provider not in self._clients:
                self._clients[provider] = self._make(provider)
            return self._clients[provider]

    def profile_of(self, game_id: str) -> LLMProfile:
        """选的那套被删了（只可能是已结束的局）就回到默认那套。"""
        pid = self._engine.game(game_id).settings.llm_profile
        if pid == DEFAULT_PROFILE:
            return self.default
        return self.profiles.get(pid) or self.default

    def __call__(self, game_id: str, judge: bool) -> tuple[LLMClient, str]:
        p = self.profile_of(game_id)
        if p.id == DEFAULT_PROFILE:
            judge_client, writer_client = self._default_clients
            return (judge_client, p.judge_model) if judge else (writer_client, p.writer_model)
        if judge:
            return self._client(p.judge_provider), p.judge_model
        return self._client(p.writer_provider), p.writer_model

    def check(self, p: LLMProfile) -> None:
        """名字和模型不能空，实现得是服务器上配好的。"""
        if not p.name.strip():
            raise ValidationFailed("llm_profile.name_required")
        for provider, model in (
            (p.judge_provider, p.judge_model),
            (p.writer_provider, p.writer_model),
        ):
            if provider not in self.providers:
                raise ValidationFailed("llm_profile.unknown_provider", provider=provider)
            if not model.strip():
                raise ValidationFailed("llm_profile.model_required")

    def check_choice(self, profile_id: str) -> None:
        if profile_id != DEFAULT_PROFILE and self.profiles.get(profile_id) is None:
            raise ValidationFailed("llm_profile.not_found", id=profile_id)
