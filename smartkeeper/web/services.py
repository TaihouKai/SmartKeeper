"""装配好的各模块实现。实例只在 web/app.py 的 build_services 里创建。"""

from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa

from smartkeeper.chat import SqlChatStore
from smartkeeper.contracts import LLMClient
from smartkeeper.engine import Engine
from smartkeeper.kp import KP
from smartkeeper.llm import SqlLLMCallLog
from smartkeeper.mapdata import FileMapStore
from smartkeeper.rules import RulesService, SqlRulePackStore


@dataclass
class Services:
    db: sa.Engine
    engine: Engine
    kp: KP
    packs: SqlRulePackStore
    rules: RulesService
    maps: FileMapStore
    llm_log: SqlLLMCallLog
    judge: LLMClient
    writer: LLMClient
    chat: SqlChatStore
    scenarios_dir: str = "scenarios"
    base_url: str = "http://localhost:8000"
