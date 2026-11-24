"""角色卡的数据结构。世界状态里的角色卡就是这个结构的 JSON 形式，JSON Patch 直接作用其上。"""

from __future__ import annotations

from typing import Literal, cast

from pydantic import Field, JsonValue, model_validator

from smartkeeper.contracts.base import Frozen


class Effect(Frozen):
    """一条修正（界面上叫“修正”）：条目在角色身上时一直生效。带 target 和 formula 的由引擎执行；
    只有描述的是概念性的，由 KP 理解。限时的修正由技能脚本的 modify 加成状态。

    formula 算出 target 的新值，和规则包里的公式一样什么都能引用；写 target 自己的名字表示
    “到这一步为止的值”（例如 move_speed * 1.2），也可以完全不管原值（例如 str + agi）。
    同一个推导值上的多个效果接力计算：固定条目 → 玩家写的条目（按 priority 从小到大）→ 状态（按添加先后）。
    """

    description: str = ""
    target: str | None = None  # 作用于哪个推导值
    formula: str | None = None
    priority: int | None = Field(default=None, ge=0)  # 玩家写的效果必填，同一张卡上不能重复

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


class ScriptStep(Frozen):
    """技能脚本的一句，数值已经算好（规划时掷骰、冻结使用者的值），生效时由引擎执行。

    - who：self 使用者，target 使用时选的对象，其他是使用者同伴的模板名
    - op：damage 受到伤害（先扣护盾 shield 再扣生命值 hp）；add / subtract / set 改 field 这个运行值；
      modify 给 field 这个推导值加一条限时修正（formula 是冻结好的新值公式）
    - seconds：add 的限时（到期扣回加上去还剩下的部分）或 modify 的持续时间；None 表示永久
    """

    who: str
    op: Literal["damage", "add", "subtract", "set", "modify", "negate"]
    field: str | None = None
    amount: float = 0
    rolls: tuple[int, ...] = ()
    seconds: int | None = None
    formula: str | None = None
    # damage：伤害类型和减免前的数（amount 是按对象模板的“受到伤害的公式”算过的）
    kind: str = ""
    raw: float | None = None


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
    # 技能设置：一串赋值（目标、射程、施放时间、冷却、范围形状、设置物……），见 smartkeeper.lang.config；
    # 解析成 SkillConfig 由 rules 负责，引擎按它执行
    config: str = ""
    # 技能脚本：用这个条目（并且 KP 判定生效）时执行的语句，见 smartkeeper.lang.script
    script: str = ""


class SkillConfig(Frozen):
    """条目的技能设置（GroupEntry.config 解析出来的）。公式都还是文本，用的时候在使用者和这一条上求值。"""

    # single：要选一个对象；self：只能对自己用；none：没有对象
    target: Literal["single", "self", "none"] = "single"
    range: str = ""  # 射程（米）；空表示不限
    visible: bool = False  # 对象必须在使用者此刻的感知里（看得见或察觉得到）
    noise: str = ""  # 动静范围（米）：范围内的其他玩家会察觉到有人用了这个技能；空表示悄无声息
    requires: str = ""  # 使用条件（公式），不成立就不能用
    cast_time: str = ""  # 施放时间（分钟）：不到 1 分钟算瞬发；用这个技能的行动至少要这么久
    cooldown: str = ""  # 冷却时间（分钟）：用过之后这么久之内不能再用
    shape: Shape | None = None  # 范围形状
    placement: PlacementSpec | None = None  # 是设置物（陷阱、结界）时的参数
    # 打没打中由引擎判：使用者做 check 里的检定（几个时都掷，取等级高的；空 = 不掷骰）。
    # auto_level 是不掷骰、直接定下的等级（公式）。等级见 CheckSpec：1 起是成功。
    # 能被应对时（reactions 列了检定或应对技能的 ID / 名字，或 reactions_any），对象是玩家的由他从中选
    # （或者不抵抗），对象是 NPC 的引擎替它挑最有利的；没发现使用者的对象不能应对。
    # hit 是命中条件（公式，可用 level、opp_level、opposed……）；不写时：成功，并且被对抗时等级高过对方。
    # difficulty 是使用者这一方的难度（公式）。save 是对象做的豁免检定（对 difficulty），脚本里 saved 是结果
    check: tuple[str, ...] = ()
    auto_level: str = ""
    difficulty: str = ""
    hit: str = ""
    reactions: tuple[str, ...] = ()
    reactions_any: bool = False
    save: str = ""

    @property
    def reactable(self) -> bool:
        return bool(self.reactions) or self.reactions_any

    @property
    def rolls(self) -> bool:
        """要不要判命中（有检定或定好的等级）。"""
        return bool(self.check) or bool(self.auto_level.strip())


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
    # 固定条目里规则包留空的列，由玩家建角时填：分组名 -> 固定条目名 -> 列名 -> 值
    # （例如每个角色的同一个技能等级各不相同）。固定条目本身不存进角色卡，读卡时把这里的值合并进去
    preset_fields: dict[str, dict[str, dict[str, JsonValue]]] = {}
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
