"""角色卡的数据结构。世界状态里的角色卡就是这个结构的 JSON 形式，JSON Patch 直接作用其上。"""

from __future__ import annotations

from typing import Literal

from pydantic import JsonValue

from smartkeeper.contracts.base import Frozen


class Effect(Frozen):
    """一个效果。带 target/op/value 的由引擎执行；只有描述的是概念性效果，由 KP 理解。"""

    description: str = ""
    target: str | None = None  # 作用于哪个推导值
    op: Literal["add", "mul"] | None = None
    value: str | None = None  # 公式；可用 self.<字段> 引用所在条目的字段

    @property
    def is_mechanical(self) -> bool:
        return self.target is not None and self.op is not None and self.value is not None


class Shape(Frozen):
    """范围形状的结构化参数，单位米、度。"""

    kind: Literal["capsule", "box", "sphere", "cone"]
    length: float | None = None
    width: float | None = None
    height: float | None = None
    radius: float | None = None
    angle: float | None = None


class GroupEntry(Frozen):
    name: str
    description: str = ""
    fields: dict[str, JsonValue] = {}
    effects: tuple[Effect, ...] = ()
    shape: Shape | None = None


class Status(Frozen):
    """带来源和游戏内到期时间（分钟）的标签，可以关联一条修正。"""

    tag: str
    source: str = ""
    expires_at: int | None = None
    modifier: Effect | None = None


class Item(Frozen):
    name: str
    description: str = ""
    qty: int = 1


class Sheet(Frozen):
    name: str
    fields: dict[str, JsonValue] = {}
    groups: dict[str, tuple[GroupEntry, ...]] = {}
    statuses: tuple[Status, ...] = ()
    items: tuple[Item, ...] = ()


class SheetSubmission(Frozen):
    """建角时提交的一个实体。"""

    template: str
    sheet: Sheet


class DerivedValue(Frozen):
    name: str
    base: float
    value: float
    modifiers: tuple[str, ...] = ()  # 修正来源的说明


class SheetChange(Frozen):
    """角色卡一个可见数值的一次变更。source 是对应的玩家可见事件序号（通常是那轮的反馈）。"""

    path: str
    old: JsonValue
    new: JsonValue
    round_no: int
    source_seq: int | None
    source_kind: Literal["feedback", "admin", "engine", "opening"]


class SheetView(Frozen):
    """给玩家看的自己实体的角色卡：隐藏字段已去掉。"""

    entity_id: str
    template: str
    sheet: dict[str, JsonValue]
    derived: tuple[DerivedValue, ...]
    history: tuple[SheetChange, ...]
