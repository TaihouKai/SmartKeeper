"""规则包的数据结构。这就是“规则”面板表单的结构，也是导入导出文件的格式。

这里不含任何具体规则体系的概念；具体的数值、模板、检定都是规则包里的数据。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, cast

from pydantic import Field, JsonValue, model_validator

from smartkeeper.contracts.base import Frozen
from smartkeeper.contracts.sheet import EntryUse, GroupEntry, ParamDef

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

FieldKind = Literal["number", "text", "resource", "boolean", "formula"]
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
    - 使用时选的数（参数）不是字段，见 ParamDef。
    - cls=player：建角时玩家填写；cls=runtime：游戏中经裁定或技能脚本修改，初值由 initial 公式给出。
      分组的列也可以是 runtime：每个条目各存一份（例如护盾开着没有），脚本里写 this.<列> 改它。
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
    # 运行值的自然变化：每分钟变化多少（公式；正数恢复、负数消耗），按上下限截断；空表示不变
    per_minute: str | None = None
    vital: bool = False  # 运行值：降到 0（或以下）时角色死亡
    # 运行值：条件公式，成立时技能脚本加不上去（治疗、补充都无效，减少照常）；自然变化（per_minute）不受影响。
    # 例如 hp_heal_blocked > 0。空是不限制
    gain_blocked: str | None = None


class ShapeDef(Frozen):
    """可重复分组的条目是否带范围形状参数（供空间查询使用）。"""

    allowed: tuple[Literal["capsule", "box", "sphere", "cone"], ...] = ()


class GroupPreset(GroupEntry):
    """规则包写好的固定条目。when 是条件公式（只能引用这张卡的字段），为真时条目出现在角色卡上；
    空表示总是出现。固定条目不存进角色卡，每次读卡时按当前字段重新算，所以不算进 min/max_count。
    fields 里没写的列（“使用时填写”的除外）由玩家建角时填，存在角色卡的 preset_fields 里。
    """

    when: str = ""


class GroupDef(Frozen):
    """可重复的分组，例如技能、特殊能力。每个条目有模板规定的字段和一个效果列表。

    条目有两种来源：玩家建角时自己写的（数量受 min/max_count 限制），和 presets 里满足条件的固定条目。
    """

    name: str
    label: str = ""
    description: str = ""  # 给建角的玩家看的说明，可以用 [[规则书的标题]] 引用规则书的一节
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
    # 物品类：条目是一件东西，本身不能直接用，只能用它的几种用途（例如一件法宝）。其他分组的条目本身就是一个动作，没有用途
    uses: bool = False
    # 用途的模板：建角时给物品加用途，可以从这里选一个照抄（例如“标准的光炮”），再按需要改
    use_templates: tuple[EntryUse, ...] = ()
    # 察觉到动静、又看得见使用者的人知不知道用的是什么（条件公式，在使用者和这一条上算，可以用 this.<列>，
    # 包括这次使用时填的数；空是知道）。由规则包定，玩家写条目时改不了。
    reveal: str = ""
    # 设了暴露条件的分组，暴露时看得见使用者的人把这个条目记进情报，同时得知使用者卡上的这些字段
    # （例如喊出名字就暴露了身份）。没设条件的分组只在动静里显示名字，不记进情报
    reveal_fields: tuple[str, ...] = ()


class BudgetDef(Frozen):
    """几个数值的合计上限，例如“六项属性合计最多 10 点”“＋ 合计最多 3 个”。

    fields：这张卡上算进去的数值字段（值就是花掉的点数，负数退回点数）；columns：“分组.列”，这个分组
    每一条（自己写的和自动获得的）这一列的值都算进去。total 是合计最多多少（公式，在这张卡上算，可以随出身变），
    空是不限、只显示合计；when 是条件公式，成立时才限制（空是总是）。只看建角时填的值，不看游戏中的临时修正。
    """

    name: str
    label: str = ""
    description: str = ""
    fields: tuple[str, ...] = ()
    columns: tuple[str, ...] = ()
    total: str = ""
    when: str = ""


class DerivedDef(Frozen):
    name: str
    label: str = ""
    formula: str
    unit: str | None = None
    hidden: bool = False


# 情报、暴露条件里写的这个名字指卡上的名字（不是字段）
NAME_FIELD = "name"


class EntityTemplate(Frozen):
    name: str
    label: str = ""
    description: str = ""  # 建角说明（这张卡怎么做），可以用 [[规则书的标题]] 引用规则书的一节
    appearance_field: str = "appearance"  # 外观描述字段名，供生成代号使用
    # 看不清样子的条件（公式，在这个角色身上算，例如进入了隐形的状态）：成立时别人只察觉得到有人在，
    # 拿不到他的外观（起外号、被攻击时的提示、KP 写给别人的反馈都一样）；自己照样看得到
    appearance_hidden: str = ""
    # 角色卡的“名字”在建角页上叫什么、怎么解释（例如“称呼：自己人怎么叫他”）。名字只有自己和 KP 看得到，
    # 别人看到的是按外观起的代号。空表示用默认的“角色名”
    name_label: str = ""
    name_hint: str = ""
    # 名字要保密（例如真名）：游戏页上自己的角色不显示名字，显示代号
    name_secret: bool = False
    # 代号：自己这一方平时怎么称呼这个角色。label / hint 是建角页上的叫法和说明（空用默认的“代号”）；
    # alias_from 是没填代号时用哪个字段的值（例如职业、类别），空表示没填就用名字
    alias_label: str = ""
    alias_hint: str = ""
    alias_from: str = ""
    fields: tuple[FieldDef, ...] = ()
    groups: tuple[GroupDef, ...] = ()
    derived: tuple[DerivedDef, ...] = ()
    budgets: tuple[BudgetDef, ...] = ()  # 合计上限（例如属性点），建角时由引擎检查
    # 受到伤害的公式：在受伤的角色身上算，amount 是原始伤害、kind 是伤害类型，结果就是实际受到的伤害
    # （不会小于 0）。例如 max(0, amount - 5 * anti_magic) if kind == "magic" else amount。空表示原样受伤
    damage_taken: str = ""
    # 隐匿：stealth 在隐匿者身上算，是观察者在 distance 米外发现它的难度（observer.<名字> 是观察者卡上的名字），
    # 0 及以下是不隐匿（空也一样）。search 是这个模板的角色当观察者时掷的骰子（公式，可以用 distance），
    # 掷出不小于难度就发现了；空表示发现不了隐匿的角色。每一轮开始时引擎替还没发现的观察者掷一次
    stealth: str = ""
    search: str = ""
    # 死亡时：这个模板的角色死掉的那一刻执行的脚本（语法同技能脚本）。self 是死者，target 是最后伤到它的角色
    # （知道时），同伴用模板名（例如主角死了让同伴开始消散：companion.set(fading, 1)）
    on_death: str = ""

    def alias_of(self, sheet: Mapping[str, Any]) -> str:
        """这张卡的代号：填了的用填的；没填按 alias_from 那个字段的值；都没有是空。"""
        alias = sheet.get("alias")
        if isinstance(alias, str) and alias.strip():
            return alias.strip()
        if self.alias_from:
            raw = sheet.get("fields")
            fields: Mapping[str, Any] = (
                cast(Mapping[str, Any], raw) if isinstance(raw, dict) else {}
            )
            v: Any = fields.get(self.alias_from)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""

    def display_name(self, sheet: Mapping[str, Any]) -> str:
        """游戏页上自己的角色显示什么：名字保密的显示代号（没有代号时用模板的显示名），否则显示名字。"""
        name = sheet.get("name")
        shown = name if isinstance(name, str) else ""
        if self.name_secret:
            return self.alias_of(sheet) or self.label or self.name
        return shown


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


class CheckDef(Frozen):
    """一个检定：名字和它的代码（一串 名字 = 值，见 rules/checkconfig.py；解析成 CheckSpec）。"""

    name: str
    config: str = ""


class CheckSpec(Frozen):
    """检定的代码解析出来的内容。结果是一个数字等级：0 及以下是失败，1 起是成功，越大越好。
    level 是算等级的公式；不写时按 success（条件）：成立是 1，不成立是 0。levels 是各等级的名字（下标就是等级）。
    公式可用变量 roll（这次掷的点数）、natural（骰子本身的点数，不含加值）、target（目标值）、
    difficulty（技能的难度，没有是 0）、distance（到对象的距离，米）、opp_roll、opp_target（对抗时对方的点数和目标值）。"""

    label: str = ""
    dice: str = ""  # 骰子公式，在执行检定的实体上求值，例如 1d100、3d6+2、1d20 + per
    target: str = "0"  # 公式，在执行检定的实体上求值
    success: str = ""
    level: str = ""
    levels: tuple[str, ...] = ()
    opposed_by: str = ""  # 对抗检定时对手做的检定；空是同一个检定


class SampleSheet(Frozen):
    """例题：一张样例角色卡和期望的推导值。"""

    name: str
    template: str
    sheet: dict[str, JsonValue]
    expected: dict[str, float]


class InsightRule(Frozen):
    """看见就知道：观察者感知到对象时，引擎自动让控制观察者的玩家得知对象卡上的这些东西（记进日志，值变了会再告诉一次）。

    observers / subjects 是模板名（空是任何模板）；when 是条件公式，在观察者身上算，target.<名字> 读对象。
    fields 是对象的字段或推导值；groups 是对象的分组：得知里面有哪些条目，以及条目建角时填的列。
    """

    name: str
    description: str = ""
    observers: tuple[str, ...] = ()
    subjects: tuple[str, ...] = ()
    when: str = ""
    fields: tuple[str, ...] = ()
    groups: tuple[str, ...] = ()


class PackParam(ParamDef):
    """规则包的默认参数：适用于 groups 里这些分组（分组名，哪个模板的都算）的每个条目。"""

    groups: tuple[str, ...] = ()


class RulePack(Frozen):
    world: WorldInfo
    templates: tuple[EntityTemplate, ...]
    player_entities: tuple[PlayerEntities, ...]
    formulas: tuple[Formula, ...] = ()
    tables: tuple[Table, ...] = ()
    checks: tuple[CheckDef, ...] = ()
    rules_text: str = ""  # 规则说明：无法结构化的规则，由 KP 阅读
    # 规则书（Markdown）：给玩家看的完整规则，网站上有单独的页面，KP 也读。
    # 规则包里的各种说明写 [[标题]] 就在那里展开规则书里这个标题下的一节
    handbook: str = ""
    samples: tuple[SampleSheet, ...] = ()
    insights: tuple[InsightRule, ...] = ()  # 看见就知道的情报
    params: tuple[PackParam, ...] = ()  # 默认参数

    @model_validator(mode="before")
    @classmethod
    def _legacy_params(cls, data: object) -> object:
        """旧格式：参数是分组里 kind=param 的列（带 spends / check / cooldown）。搬到默认参数里，只适用于那个分组。"""
        if not isinstance(data, dict):
            return data
        d = dict(cast(dict[str, Any], data))
        params: list[Any] = list(cast(list[Any], d.get("params") or []))
        templates: list[Any] = []
        for raw_t in cast(list[Any], d.get("templates") or []):
            if not isinstance(raw_t, dict):
                templates.append(raw_t)
                continue
            t = dict(cast(dict[str, Any], raw_t))
            t["fields"] = [_strip_param_keys(x) for x in cast(list[Any], t.get("fields") or [])]
            groups: list[Any] = []
            for raw_g in cast(list[Any], t.get("groups") or []):
                if not isinstance(raw_g, dict):
                    groups.append(raw_g)
                    continue
                g = dict(cast(dict[str, Any], raw_g))
                kept: list[Any] = []
                for x in cast(list[Any], g.get("fields") or []):
                    if isinstance(x, dict) and cast(dict[str, Any], x).get("kind") == "param":
                        params.append(
                            _legacy_param(cast(dict[str, Any], x), str(g.get("name", "")))
                        )
                    else:
                        kept.append(_strip_param_keys(x))
                g["fields"] = kept
                groups.append(g)
            t["groups"] = groups
            templates.append(t)
        d["templates"] = templates
        d["params"] = _merge_params(params)
        return d

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


def _strip_param_keys(f: Any) -> Any:
    if not isinstance(f, dict):
        return f
    return {
        k: v for k, v in cast(dict[str, Any], f).items() if k not in ("spends", "check", "cooldown")
    }


def _legacy_param(f: dict[str, Any], group: str) -> dict[str, Any]:
    name = str(f.get("name", ""))
    spends = f.get("spends")
    out: dict[str, Any] = {
        "name": name,
        "label": f.get("label") or "",
        "description": f.get("description") or "",
        "choices": f.get("choices") or [],
        "min": f.get("min"),
        "max": f.get("max"),
        "check": f.get("check"),
        "cooldown": f.get("cooldown"),
        "spends": spends,
        "groups": [group],
    }
    return out


def _merge_params(params: list[Any]) -> list[Any]:
    """同样定义的参数（不同分组各写了一份）合成一个，适用的分组合在一起。"""
    out: list[dict[str, Any]] = []
    for p in params:
        if not isinstance(p, dict):
            out.append(p)
            continue
        pd = cast(dict[str, Any], p)
        same = next(
            (
                o
                for o in out
                if {k: v for k, v in o.items() if k != "groups"}
                == {k: v for k, v in pd.items() if k != "groups"}
            ),
            None,
        )
        if same is not None:
            same["groups"] = [
                *same.get("groups", []),
                *[g for g in pd.get("groups", []) if g not in same.get("groups", [])],
            ]
        else:
            out.append(dict(pd))
    return out
