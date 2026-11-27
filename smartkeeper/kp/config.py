from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True)
class KPConfig:
    """KP 管线的配置。用哪套模型按局选，不在这里（见 KP 的 models）。"""

    writer_concurrency: int = 4  # 反馈撰写的最大并行数
    max_retries: int = 2  # JSON 解析或校验失败后的重试次数
    recent_rounds: int = 3  # 裁定上下文里放原文的最近轮数
    history_events: int = 300  # 玩家视图最多放多少条事件
    memory_budget_chars: int = 20000  # 记事条目展开成原文的长度预算
    claim_chunk_events: int = 400  # 声明核对时玩家视图每段的事件数
    leak_check: bool = True  # 每份反馈过模型泄密检查（确定性的检查总是做）
    rolling_summary: bool = True  # 每轮发布后更新滚动摘要
    # 界面翻译表（语言 -> 键 -> 文字）：审核角色卡时把技能代码写成句子用其中的 ex.*；空的话不给效果说明
    messages: Mapping[str, Mapping[str, str]] = field(default_factory=dict[str, Mapping[str, str]])
