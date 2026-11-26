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
    entry: str | None = None  # 用了哪个技能（条目名或 ID）：耗时至少是它的施放时间
    move_seconds: int = Field(default=0, ge=0)  # 走到 destination 的耗时，由引擎算
    params: dict[str, float] = {}  # 用技能时选的参数（界面上选的；没选的按默认）
    # 一起走：同一个值的几条（不同的角色）移动耗时取其中最慢的，一起出发、一起到
    group: str | None = None


class ComposedAction(Frozen):
    """玩家在界面上点出来的一条行动（不经过 KP 解析）：actor 去 destination（companions 和他一起走），
    和/或者用 entry 这个技能（对 target，参数 params）。都是实体 id。"""

    actor: str
    destination: Location | None = None
    companions: tuple[str, ...] = ()
    entry: str | None = None
    target: TargetRef | None = None
    params: dict[str, float] = {}


class Step(Frozen):
    """进行中行动的一步：先从 start 移动到 to（move 秒），再做动作（act 秒）。"""

    item: str  # 行动条目 id
    targets: tuple[str, ...] = ()  # 条目以之为目标的实体
    start: Point | None = None
    to: Location | None = None
    move: int = 0
    act: int = 0
    fly: bool = False  # 飞过去（直线）还是走过去（先竖直再水平）
    # 这一步用的技能：动作做完的那一刻由引擎执行（结算时），参数是玩家选的
    entry: str | None = None
    params: dict[str, float] = {}


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
    # 玩家写的补充文字和他在界面上点的行动矛盾：KP 写下原因，不能提交
    conflict: str = ""
