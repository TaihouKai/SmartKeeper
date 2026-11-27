"""装配好的各模块实现。实例只在 web/app.py 的 build_services 里创建。"""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlalchemy as sa

from smartkeeper.chat import SqlChatStore
from smartkeeper.contracts import Dice
from smartkeeper.copilot import Copilot
from smartkeeper.engine import Engine
from smartkeeper.kp import KP
from smartkeeper.llm import SqlLLMCallLog
from smartkeeper.mapdata import FileMapStore
from smartkeeper.rules import RulesService, SqlRulePackStore
from smartkeeper.web.llm_router import LLMRouter


@dataclass
class Services:
    db: sa.Engine
    engine: Engine
    kp: KP
    packs: SqlRulePackStore
    rules: RulesService
    maps: FileMapStore
    llm_log: SqlLLMCallLog
    llm: LLMRouter  # 每局用哪套模型
    chat: SqlChatStore
    dice: Dice  # 规则编辑器的试运行用；对局里的随机数只由 engine 产生
    copilot: Copilot
    # 界面的翻译表（导出 PDF 这类后端要写成文字的地方用）
    messages: dict[str, dict[str, str]] = field(default_factory=dict[str, dict[str, str]])
    scenarios_dir: str = "scenarios"
    base_url: str | None = None  # 没配置时邀请链接用管理员打开控制台时的地址
    # 模型价格（美元 / 百万 token：输入、命中缓存的输入、输出），按模型名前缀匹配
    model_prices: dict[str, tuple[float, float, float]] = field(
        default_factory=dict[str, tuple[float, float, float]]
    )
