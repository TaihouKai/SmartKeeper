from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KPConfig:
    """KP 管线的配置。模型选择是全局配置，不按局设置。"""

    judge_model: str = "claude-opus-5-5"  # 开场、检定规划、回合裁定
    writer_model: str = "claude-opus-5-5"  # 其余调用
    writer_concurrency: int = 4  # 反馈撰写的最大并行数
    max_retries: int = 2  # JSON 解析或校验失败后的重试次数
    recent_rounds: int = 3  # 裁定上下文里放原文的最近轮数
    history_events: int = 300  # 玩家视图最多放多少条事件
    memory_budget_chars: int = 20000  # 记事条目展开成原文的长度预算
    claim_chunk_events: int = 400  # 声明核对时玩家视图每段的事件数
    leak_check: bool = True  # 每份反馈过模型泄密检查（确定性的检查总是做）
    rolling_summary: bool = True  # 每轮发布后更新滚动摘要
