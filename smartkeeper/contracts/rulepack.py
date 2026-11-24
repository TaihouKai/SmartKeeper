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

    - kind=number：数值（属性、技能、玩家自定义的尺寸等）；可带 unit、min、max。choices 非空时只能取
      其中的值：名字=数（E=1）、数（10）、范围（1~5），见 rules/choices.py；存的是数。
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
    placements: bool = True  # 条目是否可以是设置物（陷阱、结界等）
    timing: bool = True  # 条目是否有施放时间和冷却时间（技能）
    reactions: bool = True  # 条目可以当反应（被攻击时用来应对；只有瞬发的才行）
    # 这个分组的条目在技能脚本里造成的伤害是什么类型（例如 magic）；damage(数量, "类型") 可以单独指定
    damage_kind: str = ""
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
    # 受到伤害的公式：在受伤的角色身上算，amount 是原始伤害、kind 是伤害类型，结果就是实际受到的伤害
    # （不会小于 0）。例如 max(0, amount - 5 * anti_magic) if kind == "magic" else amount。空表示原样受伤
    damage_taken: str = ""


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


# 检定的结果等级：固定四个
type CheckLevel = Literal["critical_success", "success", "failure", "critical_failure"]
CHECK_LEVELS: tuple[CheckLevel, ...] = (
    "critical_success",
    "success",
    "failure",
    "critical_failure",
)


class CheckDef(Frozen):
    """一个检定：名字和它的代码（一串 名字 = 值，见 rules/checkconfig.py；解析成 CheckSpec）。"""

    name: str
    config: str = ""


class CheckSpec(Frozen):
    """检定的代码解析出来的内容。结果按顺序判断：大成功、大失败、成功的条件，第一个成立的就是结果；都不成立是失败。
    条件是公式，可用变量 roll（这次掷的点数）、natural（骰子本身的点数，不含加值）、target（目标值）、
    difficulty（难度；对抗时是对方的点数）、opp_roll、opp_target（对抗时对方的点数和目标值）。"""

    label: str = ""
    dice: str = ""  # 骰子公式，在执行检定的实体上求值，例如 1d100、3d6+2、1d20 + per
    target: str = "0"  # 公式，在执行检定的实体上求值
    critical_success: str = "False"
    success: str = ""
    critical_failure: str = "False"
    opposed_by: str = ""  # 对抗检定时对手做的检定；空是同一个检定


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
