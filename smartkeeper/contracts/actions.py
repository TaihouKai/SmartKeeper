"""行动声明的结构化意图。"""

from __future__ import annotations

from typing import Literal

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
