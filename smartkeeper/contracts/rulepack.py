"""规则包的数据结构。这就是“规则”面板表单的结构，也是导入导出文件的格式。

这里不含任何具体规则体系的概念；具体的数值、模板、检定都是规则包里的数据。
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, JsonValue

from smartkeeper.contracts.base import Frozen
from smartkeeper.contracts.sheet import GroupEntry

# 引擎必需的推导值。每个实体模板都必须为它们提供公式。
REQUIRED_DERIVED: tuple[str, ...] = (
    "perception_radius",
    "concealment",
    "move_speed",
    "fly_multiplier",
    "fly_speed",
    "hear_multiplier",
    "hear_distance",
)
# 引擎必需的字段：每个模板都必须有这个“是/否”字段，决定移动按飞行还是地面计算。
FLY_FIELD = "can_fly"
# 每个模板都必须有生命值：运行值（数值或资源）。引擎扣伤害时按 SHIELD_FIELD（有的话）→ HP_FIELD 的顺序。
HP_FIELD = "hp"
SHIELD_FIELD = "shield"
# 致命运行值归零时引擎加的状态；冷却中的技能是 COOLDOWN_TAG + 技能名
DEAD_TAG = "dead"
COOLDOWN_TAG = "cooldown:"

FieldKind = Literal["number", "text", "resource", "boolean", "formula", "param"]
FieldClass = Literal["player", "runtime"]


class WorldInfo(Frozen):
    name: str
    description: str = ""
    canon: str = ""  # 以哪部作品或哪个版本为准
    reference_sites: tuple[str, ...] = ()


class FieldDef(Frozen):
    """角色卡上的一个字段。

    - kind=number：数值（属性、技能、玩家自定义的尺寸等）；可带 unit、min、max。
    - kind=text：文字；choices 非空时只能取其中之一。
    - kind=resource：有上下限的数值。上下限可以是公式（例如引用某个推导值）。
    - kind=boolean：是/否。公式里是 1/0。没填时按“否”。
    - kind=formula：掷骰公式（例如技能的伤害 1d str）。平时不算，KP 裁定时要求引擎掷一次才算；
      在分组的条目里可以用 this.<字段> 引用这个条目的字段。
    - kind=param：使用时填写的数（只在分组里），例如这次消耗多少魔力。不存进角色卡；KP 按玩家的行动
      在掷骰时给出，引擎检查 min..max（公式，可以用 this.<字段>），spends 给了资源字段名时还检查够不够，
      并在这一轮结算时从那个资源里扣掉。掷骰公式里用 this.<字段> 引用这次填的数。
    - cls=player：建角时玩家填写；cls=runtime：游戏中经裁定修改，初值由 initial 公式给出。
    """

    name: str
    label: str = ""
    description: str = ""  # 给玩家看的一句说明，例如“运动能力、近战、力气”
    kind: FieldKind
    cls: FieldClass = "player"
    unit: str | None = None
    min: str | None = None  # 公式
    max: str | None = None  # 公式
    initial: str | None = None  # 公式；runtime 字段建角时的初值
    choices: tuple[str, ...] = ()
    required: bool = True
    hidden: bool = False  # 对玩家隐藏
    spends: str | None = None  # kind=param：从角色的哪个资源字段里扣
    # 运行值的自然变化：每分钟变化多少（公式；正数恢复、负数消耗），按上下限截断；空表示不变
    per_minute: str | None = None
    vital: bool = False  # 运行值：降到 0（或以下）时角色死亡


class ShapeDef(Frozen):
    """可重复分组的条目是否带范围形状参数（供空间查询使用）。"""

    allowed: tuple[Literal["capsule", "box", "sphere", "cone"], ...] = ()


class GroupPreset(GroupEntry):
    """规则包写好的固定条目。when 是条件公式（只能引用这张卡的字段），为真时条目出现在角色卡上；
    空表示总是出现。固定条目不存进角色卡，每次读卡时按当前字段重新算，所以不算进 min/max_count。
    """

    when: str = ""


class GroupDef(Frozen):
    """可重复的分组，例如技能、特殊能力。每个条目有模板规定的字段和一个效果列表。

    条目有两种来源：玩家建角时自己写的（数量受 min/max_count 限制），和 presets 里满足条件的固定条目。
    """

    name: str
    label: str = ""
    fields: tuple[FieldDef, ...] = ()
    presets: tuple[GroupPreset, ...] = ()
    min_count: int = 0
    max_count: int | None = None
    effects: bool = True  # 条目是否可以带效果
    shapes: ShapeDef = ShapeDef()
    placements: bool = False  # 条目是否可以是设置物（陷阱、结界等）
    timing: bool = False  # 条目是否有施放时间和冷却时间（技能）
    hidden: bool = False


class DerivedDef(Frozen):
    name: str
    label: str = ""
    formula: str
    unit: str | None = None
    hidden: bool = False


class EntityTemplate(Frozen):
    name: str
    label: str = ""
    appearance_field: str = "appearance"  # 外观描述字段名，供生成代号使用
    fields: tuple[FieldDef, ...] = ()
    groups: tuple[GroupDef, ...] = ()
    derived: tuple[DerivedDef, ...] = ()


class PlayerEntities(Frozen):
    """一个玩家建角时要创建哪些模板的实体、各几个。"""

    template: str
    min: int = 1
    max: int = 1


class Table(Frozen):
    """查表。kind=range：取不超过键值的最大一行；kind=exact：键必须完全相等。"""

    name: str
    kind: Literal["range", "exact"] = "range"
    rows: tuple[tuple[float | str, float], ...]


class Formula(Frozen):
    """命名公式，可在其他公式里按名字引用。"""

    name: str
    formula: str
    label: str = ""


class ResultLevel(Frozen):
    """检定的一个结果等级。按顺序判断，第一个条件为真的等级就是结果。"""

    name: str
    condition: str  # 公式；可用变量 roll、target、difficulty、opp_roll、opp_target


class CheckDef(Frozen):
    name: str
    label: str = ""
    dice: str  # 骰子公式，在执行检定的实体上求值，例如 1d100、3d6+2、1d str
    target: str = "0"  # 公式，在执行检定的实体上求值
    levels: tuple[ResultLevel, ...]
    opposed_by: str | None = None  # 对抗检定时对手做的检定，默认同名检定


class SampleSheet(Frozen):
    """例题：一张样例角色卡和期望的推导值。"""

    name: str
    template: str
    sheet: dict[str, JsonValue]
    expected: dict[str, float]


class RulePack(Frozen):
    world: WorldInfo
    templates: tuple[EntityTemplate, ...]
    player_entities: tuple[PlayerEntities, ...]
    formulas: tuple[Formula, ...] = ()
    tables: tuple[Table, ...] = ()
    checks: tuple[CheckDef, ...] = ()
    rules_text: str = ""  # 规则说明：无法结构化的规则，由 KP 阅读
    samples: tuple[SampleSheet, ...] = ()

    def template(self, name: str) -> EntityTemplate | None:
        return next((t for t in self.templates if t.name == name), None)

    def check(self, name: str) -> CheckDef | None:
        return next((c for c in self.checks if c.name == name), None)


class RulePackVersion(Frozen):
    pack_id: str
    version: int
    pack: RulePack
    created_at: str = Field(default="")


class RulePackInfo(Frozen):
    pack_id: str
    name: str
    versions: tuple[int, ...]
    draft_updated_at: str | None = None  # 有没写完的草稿时是它的保存时间


class RulePackDraft(Frozen):
    """没写完的规则包：只检查结构能不能读，不做内容校验，不能用来开局。每个规则包最多一份。"""

    pack_id: str
    pack: RulePack
    updated_at: str
