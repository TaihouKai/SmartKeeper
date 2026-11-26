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
    # 作用于哪个数值：推导值或数值字段（例如力量）；<条目名>.<列> 是某个条目的一列（限时修正用）
    target: str | None = None
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
      modify 给 field 这个数值（推导值、字段）加一条限时修正（formula 是冻结好的新值公式）。
      field 写成 this.<列> 时是使用的这个条目的列（运行中会变的列，或 modify 修正的列）；
      summon 召唤 amount 个 field 这个模板的角色；teleport 瞬间移动到 to 身边；
      locate 使用者这一方掌握了 who 此刻的位置（记一次目击）
    - seconds：add 的限时（到期扣回加上去还剩下的部分）或 modify 的持续时间；None 表示永久
    """

    who: str
    op: Literal[
        "damage", "add", "subtract", "set", "modify", "negate", "summon", "teleport", "locate"
    ]
    field: str | None = None
    amount: float = 0
    rolls: tuple[int, ...] = ()
    seconds: int | None = None
    formula: str | None = None
    # damage：伤害类型和减免前的数（amount 是按对象模板的“受到伤害的公式”算过的）
    kind: str = ""
    raw: float | None = None
    # summon：模板（field）、几个（amount）、存在多久（seconds），新角色卡上的字段；teleport：移动到谁身边（to，接收者）
    values: dict[str, JsonValue] = {}
    to: str | None = None


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

    radius: str = ""  # 触发范围（米），圆形；building 时不用
    # 设置者所在的整栋建筑就是这个设置物（例如把一栋楼做成据点）：条件公式，可以按参数选；空是否
    building: str = ""
    perceive_multiplier: str = "1"  # 别人发现它的距离 = 那人的感知半径 × 这个系数；0 表示发现不了
    charges: str = ""  # 可触发次数；空表示无限
    duration: str = ""  # 持续多少秒；空表示一直存在，直到被移除
    notify_owner: bool = True  # 被触发时是否通知设置者


class ParamDef(Frozen):
    """使用时选的参数（例如“全力发动”“额外加强”“投入多少法力”）。不存进角色卡；KP 按玩家的行动在用的时候给出，
    没给的取第一个可选值（没有可选值时取下限）。公式和脚本里 this.<name> 是这次选的数。

    一次使用实际有的参数 = 规则包的默认参数（适用于这个分组的）+ 条目上加的 + 用途上加的（同名的后者覆盖前者）。
    下面这些只在选了非 0 时起作用：
    - requires：能不能选（条件公式，在使用者和条目上算），不成立就拒绝这次使用；
    - check：要过的检定，没过按 0 算（不扣、不放大）；
    - cooldown：选过以后这个条目多久（分钟）不能再选；
    - spends：从使用者的哪个资源里扣，扣的数就是选的数（例如投入多少魔力），不够时拒绝；
    - script：选了就执行的句子（例如扣同伴身上的资源：mentor.sub(charges, 1)），不管这次打没打中都执行；
    - multiplier：效果倍数（公式），这次使用的伤害、治疗、增加的数值自动乘上去（消耗不乘），脚本里 boost 是总倍数；
    - duration：用在被动的条目（没有设置也没有脚本）上时，接下来多少分钟里这个条目的数值列乘上倍数；空表示不行。
    by_kp：这个数由 KP 按局面定（例如所在地的地脉强弱），不是使用者自己选的。
    """

    name: str
    label: str = ""
    description: str = ""
    choices: tuple[str, ...] = ()
    min: str | None = None
    max: str | None = None
    requires: str = ""
    check: str | None = None
    cooldown: str | None = None
    spends: str | None = None
    script: str = ""
    multiplier: str = ""
    duration: str = ""
    by_kp: bool = False


class EntryUse(Frozen):
    """物品的一种用法（例如一把枪：枪托砸人、射击），每种用法是一个技能。只有物品类的分组（GroupDef.uses）的条目有用途。

    用的时候写“条目名/用途名”。公式里 this.<列> 是物品的列。只写说明、不写设置和脚本的用途由 KP 按说明裁定。
    toggle：这是一个开关（例如开关风之结界）：每用一次切换开/关，default_on 是一开始开着没有；
    effects 是开着的时候生效的修正。脚本里 turning_on 是这一次是不是打开。
    """

    name: str
    description: str = ""
    config: str = ""
    script: str = ""
    params: tuple[ParamDef, ...] = ()  # 只有这个用途有的参数
    toggle: bool = False
    default_on: bool = False
    effects: tuple[Effect, ...] = ()  # 旧格式；新写的在 bonus 里
    bonus: str = ""  # 开着的时候的常驻加成（代码，见 smartkeeper.lang.bonus）


USE_SEP = "/"  # 条目名/用途名


class GroupEntry(Frozen):
    name: str
    # 引用用的英文 ID（例如 attack_magic）：公式里 master.attack_magic 表示有没有这一条（1/0），
    # master.attack_magic.level 是这一条的 level 列。不填就不能被引用。
    id: str = ""
    description: str = ""
    fields: dict[str, JsonValue] = {}
    effects: tuple[Effect, ...] = ()  # 旧格式；新写的在 bonus 里
    # 常驻加成（代码，见 smartkeeper.lang.bonus）：一行一条 self.<名字> += …，可以有 if；一直生效
    bonus: str = ""
    # 技能设置：一串赋值（目标、射程、施放时间、冷却、范围形状、设置物……），见 smartkeeper.lang.config；
    # 解析成 SkillConfig 由 rules 负责，引擎按它执行
    config: str = ""
    # 技能脚本：用这个条目（并且 KP 判定生效）时执行的语句，见 smartkeeper.lang.script
    script: str = ""
    # 物品的几种用法（见 EntryUse）；只有物品类分组的条目有，物品本身不能直接用
    uses: tuple[EntryUse, ...] = ()
    # 这个条目加的参数（物品的话所有用途共用），加在规则包的默认参数后面
    params: tuple[ParamDef, ...] = ()


class SkillConfig(Frozen):
    """条目的技能设置（GroupEntry.config 解析出来的）。公式都还是文本，用的时候在使用者和这一条上求值。"""

    # single：要选一个对象；self：只能对自己用；none：没有对象
    target: Literal["single", "self", "none"] = "single"
    range: str = ""  # 射程（米）；空表示不限
    visible: bool = False  # 对象必须在使用者此刻的感知里（看得见或察觉得到）
    # 对象的位置要在这么多分钟之内掌握过（公式）：使用者这一方（玩家的所有角色算一起）亲眼察觉到、
    # 别人转告、或者用技能找到（target.locate()）都算；此刻察觉得到是 0。空表示不要求
    seen_within: str = ""
    noise: str = ""  # 动静范围（米）：范围内的其他玩家会察觉到有人用了这个技能；空表示悄无声息
    requires: str = ""  # 使用条件（公式），不成立就不能用
    cast_time: str = ""  # 施放时间（分钟）：不到 1 分钟算瞬发；用这个技能的行动至少要这么久
    cooldown: str = ""  # 冷却时间（分钟）：用过之后这么久之内不能再用
    shape: Shape | None = None  # 范围形状
    # 影响谁：all 所有人；allies 友军（自己这一方和结盟的玩家的角色，包括自己）；other_allies 除了自己以外的友军；
    # enemies 只有不是友军的。
    # 范围技能按它筛选形状里的人；单体技能的对象不符合时不能用
    affects: Literal["all", "allies", "other_allies", "enemies"] = "all"
    # 光环（被动）：以自己为中心的球（只能 sphere），里面符合 affects 的人（包括自己）一直带着这一条的常驻加成；
    # 每轮开始时按位置重算，进圈就有、出圈就没。光环条目的常驻加成不再按普通方式只加在自己身上
    aura: Shape | None = None
    # 守护（和光环一起用）：圈里符合 affects 的人受光环主人守护，敌人对他们用的技能（单体和范围）落到光环主人身上
    guard: bool = False
    placement: PlacementSpec | None = None  # 是设置物（陷阱、结界）时的参数
    # 写定的参数：参数名 -> 值（公式）。这个技能用的时候这个参数就是这个值，不用再选
    # （例如某个用途每次都要付某种代价）。开关类用途关上时不算参数
    fixed: dict[str, str] = {}
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


class PresetEdit(Frozen):
    """玩家对一个固定条目（规则包给的、自动获得的）的修改：写了的部分换掉规则包的，None 是不改。
    名字和 ID 不能改（别处按它们引用）；规则包定了的列也不能改（留空的列在 preset_fields 里填）。"""

    description: str | None = None
    config: str | None = None
    bonus: str | None = None  # 改了常驻加成时，规则包旧格式的 effects 一起换掉
    script: str | None = None
    params: tuple[ParamDef, ...] | None = None
    uses: tuple[EntryUse, ...] | None = None


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
    # 玩家改过的固定条目：分组名 -> 固定条目名 -> 改了什么（见 PresetEdit）
    preset_edits: dict[str, dict[str, PresetEdit]] = {}
    # 开关类用途现在开着没有：“条目名/用途名” -> 是否开着；没有记录的按用途的 default_on
    toggles: dict[str, bool] = {}
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


class ExplainLine(Frozen):
    """技能设置、脚本、常驻加成写成的一句话（给人读的）；depth 是缩进层级（如果……下面的句子缩进一层）。"""

    depth: int = 0
    text: str


class BudgetUse(Frozen):
    """一张卡在一项合计上限上用了多少：total 是 None 表示不限（或算不出来）；active 是条件成立（不成立的不用管）。"""

    name: str
    label: str = ""
    description: str = ""
    used: float
    total: float | None = None
    active: bool = True


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
