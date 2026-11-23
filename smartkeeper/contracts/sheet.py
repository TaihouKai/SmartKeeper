"""角色卡的数据结构。世界状态里的角色卡就是这个结构的 JSON 形式，JSON Patch 直接作用其上。"""

from __future__ import annotations

from typing import Literal, cast

from pydantic import Field, JsonValue, model_validator

from smartkeeper.contracts.base import Frozen


class Effect(Frozen):
    """一个效果。带 target 和 formula 的由引擎执行；只有描述的是概念性效果，由 KP 理解。

    formula 算出 target 的新值，和规则包里的公式一样什么都能引用；写 target 自己的名字表示
    “到这一步为止的值”（例如 move_speed * 1.2），也可以完全不管原值（例如 str + agi）。
    同一个推导值上的多个效果接力计算：固定条目 → 玩家写的条目（按 priority 从小到大）→ 状态（按添加先后）。
    """

    description: str = ""
    target: str | None = None  # 作用于哪个推导值
    formula: str | None = None
    priority: int | None = Field(default=None, ge=0)  # 玩家写的效果必填，同一张卡上不能重复
    # 持续时间（秒，公式）：空表示被动常驻（条目在就生效）；填了就只在使用时加到作用对象身上，到期消失。
    # 这时公式里这个推导值自己的名字指对象的值，其余名字取施法者施法那一刻的值。
    duration: str = ""

    @model_validator(mode="before")
    @classmethod
    def _legacy_op(cls, data: object) -> object:
        """旧格式 {op: add|mul, value} 换成一个公式。"""
        if isinstance(data, dict) and "op" in data:
            d = dict(cast(dict[str, object], data))
            op, value, target = d.pop("op", None), d.pop("value", None), d.get("target")
            if op in ("add", "mul") and isinstance(value, str) and isinstance(target, str):
                d["formula"] = f"{target} {'+' if op == 'add' else '*'} ({value})"
            return d
        return cast(object, data)

    @property
    def is_mechanical(self) -> bool:
        return self.target is not None and self.formula is not None


class OnUse(Frozen):
    """作用效果：条目被使用（并且 KP 判定生效）时由引擎执行的一项状态改变。

    - who：作用在对象（target）还是自己（self）身上
    - op：damage 受到伤害（先扣护盾 shield 再扣生命值 hp）；add / subtract / set 改 field 这个运行值
    - amount：数量公式，可以掷骰；名字取施法者这边，self.<列> 是这一条的列，target.x 是对象的
    - duration：只对 add 有意义，秒（公式）；到期时把加上去还剩下的部分扣回
    """

    description: str = ""
    who: Literal["target", "self"] = "target"
    op: Literal["damage", "add", "subtract", "set"] = "damage"
    field: str | None = None
    amount: str
    duration: str = ""


class Grant(Frozen):
    """限时加上的运行值（例如护盾）：到期时扣回还剩下的部分。"""

    field: str
    amount: float


class Shape(Frozen):
    """范围形状的结构化参数，单位米、度。"""

    kind: Literal["capsule", "box", "sphere", "cone"]
    length: float | None = None
    width: float | None = None
    height: float | None = None
    radius: float | None = None
    angle: float | None = None


class PlacementSpec(Frozen):
    """条目是设置物（陷阱、结界等）时的参数。都是公式，在设置者的角色卡和这个条目上求值，设置时算定。"""

    radius: str  # 触发范围（米），圆形
    perceive_multiplier: str = "1"  # 别人发现它的距离 = 那人的感知半径 × 这个系数；0 表示发现不了
    charges: str = ""  # 可触发次数；空表示无限
    duration: str = ""  # 持续多少秒；空表示一直存在，直到被移除
    notify_owner: bool = True  # 被触发时是否通知设置者


class GroupEntry(Frozen):
    name: str
    # 引用用的英文 ID（例如 attack_magic）：公式里 master.attack_magic 表示有没有这一条（1/0），
    # master.attack_magic.level 是这一条的 level 列。不填就不能被引用。
    id: str = ""
    description: str = ""
    fields: dict[str, JsonValue] = {}
    effects: tuple[Effect, ...] = ()
    shape: Shape | None = None
    placement: PlacementSpec | None = None
    actions: tuple[OnUse, ...] = ()  # 作用效果
    # 施放时间（分钟，公式）：不到 1 分钟算瞬发。用这个技能的行动至少要这么久
    cast_time: str = ""
    # 冷却时间（分钟，公式）：用过之后这么久之内不能再用
    cooldown: str = ""


class Status(Frozen):
    """带来源和游戏内到期时间（分钟）的标签，可以关联一条修正。"""

    tag: str
    source: str = ""
    expires_at: int | None = None  # 游戏内秒
    modifier: Effect | None = None
    grant: Grant | None = None


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
