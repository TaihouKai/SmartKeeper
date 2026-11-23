"""行动声明的结构化意图。"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from smartkeeper.contracts.base import Frozen
from smartkeeper.contracts.geometry import Location, Point


class TargetRef(Frozen):
    kind: Literal["entity", "feature", "point"]
    id: str | None = None
    point: Point | None = None


class ActionItem(Frozen):
    """一个行动条目。id 由引擎在写入 action_declared 时分配，解析结果里为空。"""

    id: str | None = None
    actor: str  # 执行者：该玩家控制的某个实体
    verb: str
    targets: tuple[TargetRef, ...] = ()
    destination: Location | None = None
    detail: str = ""
    act_seconds: int = Field(default=0, ge=0)  # 动作本身的耗时，解析时由 KP 估算，不含移动
    move_seconds: int = Field(default=0, ge=0)  # 走到 destination 的耗时，由引擎算


class Step(Frozen):
    """进行中行动的一步：先从 start 移动到 to（move 秒），再做动作（act 秒）。"""

    item: str  # 行动条目 id
    targets: tuple[str, ...] = ()  # 条目以之为目标的实体
    start: Point | None = None
    to: Location | None = None
    move: int = 0
    act: int = 0
    fly: bool = False  # 飞过去（直线）还是走过去（先竖直再水平）


class Activity(Frozen):
    """一个实体进行中的行动（世界状态 /activities/<实体 id>）。只有引擎能写。"""

    player: str
    start: int  # 开始时刻（秒）
    end: int  # 结束时刻（秒）
    steps: tuple[Step, ...]


class ClaimRef(Frozen):
    """行动里对往事的引用，例如“我以前打过 @某人 一巴掌”。"""

    text: str
    entities: tuple[str, ...] = ()
    features: tuple[str, ...] = ()


class Intent(Frozen):
    items: tuple[ActionItem, ...]
    claims: tuple[ClaimRef, ...] = ()
    quotes: tuple[int, ...] = ()  # 玩家用“引用”按钮引用的事件序号
    unresolved: tuple[str, ...] = ()  # 对应不上的指代；非空时不能提交
