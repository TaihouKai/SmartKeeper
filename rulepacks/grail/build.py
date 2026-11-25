"""圣杯战争规则包：以本人的规则书 v2026 为参考，按型月的设定和玩法写成引擎的规则包。

    uv run python rulepacks/grail/build.py      # 写出 rulepacks/grail/pack.json（导入格式）并校验

原则：跑团沙盒，不求平衡，RP、合理、简单优先；规则书只作参考。引擎能执行的都在这里，交给 KP 的写在 RULES_TEXT。

型月里决定玩法的几件事，这里都落到了规则上：
- 御主和英灵一组：御主是弱点（死了英灵就开始消散），英灵靠御主的魔力存在；
- 令咒：三划，绝对命令、空间转移、魔力灌注、自害；
- 真名：英灵对外只叫职阶；宝具平时用不暴露名字，解放真名时喊出来，附近的人听得到；
- 神秘：普通的攻击伤不到英灵，只有魔术、礼装、英灵和宝具的攻击才行；灵体化时物理上碰不到；
- 宝具是“装备”：一件宝具有等级、类型和常驻效果，下面挂几种用法（平时当武器用、开关、解放真名的光炮、结界、召唤……），
  不能写成规则的效果写成说明，由 KP 裁定；
- 职阶技能按职阶出现，等级建角时自己填；魔术师有工房，Caster 有阵地，在里面回魔快；
- 使魔、傀儡兵、宝具召唤的军势是召唤物，由玩家控制，共享感知。
"""

from __future__ import annotations

import sys
from pathlib import Path
from textwrap import dedent
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).with_name("pack.json")

CLASSES = ["Saber", "Archer", "Lancer", "Rider", "Caster", "Assassin", "Berserker"]
RANKS = ["E=1", "D=2", "C=3", "B=4", "A=5", "EX=10"]
PLUS = ["无=0", "+=1", "++=2", "+++=3"]
LEVELS = '["失败", "成功", "困难成功", "极难成功"]'
BACKGROUNDS = ["普通人", "魔术师", "人造人", "魔术使", "代行者", "其他"]

# 三档：>10 成功、>15 困难成功、>20 极难成功（难度加在需要的点数上；打使魔再难 5）；
# 英灵和召唤的军势对人类至少困难成功
_R = '(roll - difficulty - (5 if opponent.template == "familiar" else 0))'
TIERS = (
    "level = max(\n"
    f"    0 if {_R} <= 10 else 1 if {_R} <= 15 else 2 if {_R} <= 20 else 3,\n"
    '    2 if (self.template == "servant" or self.template == "squad") '
    'and opponent.template == "master" else 0,\n'
    ")"
)


def code(text: str) -> str:
    return dedent(text).strip("\n")


def check(name: str, label: str, dice: str) -> dict[str, Any]:
    return {"name": name, "config": f'label = "{label}"\ndice = {dice}\n{TIERS}\nlevels = {LEVELS}'}


def field(name: str, label: str, kind: str, cls: str = "player", **kw: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "name": name,
        "label": label,
        "description": kw.pop("description", ""),
        "kind": kind,
        "cls": cls,
        "required": kw.pop("required", True),
        "hidden": kw.pop("hidden", False),
        "choices": kw.pop("choices", []),
        "vital": kw.pop("vital", False),
    }
    out.update(kw)
    return out


def derived(name: str, label: str, formula: str, unit: str | None = None) -> dict[str, Any]:
    return {"name": name, "label": label, "formula": formula, "unit": unit, "hidden": False}


def use(name: str, desc: str, config: str = "", script: str = "") -> dict[str, Any]:
    return {"name": name, "description": desc, "config": code(config), "script": code(script)}


def preset(
    name: str, pid: str, desc: str, config: str = "", script: str = "", **kw: Any
) -> dict[str, Any]:
    return {
        "name": name,
        "id": pid,
        "description": desc,
        "fields": kw.pop("fields", {}),
        "effects": kw.pop("effects", []),
        "config": code(config),
        "script": code(script),
        "when": kw.pop("when", ""),
        "uses": kw.pop("uses", []),
    }


def effect(desc: str, target: str, formula: str) -> dict[str, Any]:
    return {"description": desc, "target": target, "formula": formula, "priority": None}


def group(name: str, label: str, presets: list[dict[str, Any]], **kw: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "name": name,
        "label": label,
        "fields": kw.pop("fields", []),
        "presets": presets,
        "min_count": 0,
        "max_count": kw.pop("max_count", 0),
        "effects": kw.pop("effects", True),
        "shapes": {"allowed": kw.pop("shapes", [])},
        "hidden": kw.pop("hidden", False),
        "placements": kw.pop("placements", False),
        "timing": kw.pop("timing", True),
        "reactions": kw.pop("reactions", False),
        "damage_kind": kw.pop("damage_kind", ""),
        "use_templates": kw.pop("use_templates", []),
    }
    out.update(kw)
    return out


def table(name: str, rows: list[tuple[Any, float]], kind: str = "exact") -> dict[str, Any]:
    return {"name": name, "kind": kind, "rows": [list(r) for r in rows]}


def by_class(values: list[float]) -> list[tuple[Any, float]]:
    return list(zip(CLASSES, values, strict=True))


def by_rank(values: list[float]) -> list[tuple[Any, float]]:
    """E~A、EX 的表。按范围查：被“+”或狂化抬高到两档之间的等级取低的那一档。"""
    return list(zip([1, 2, 3, 4, 5, 10], values, strict=True))


def is_class(*names: str) -> str:
    return " or ".join(f'klass == "{n}"' for n in names)


# ======================= 共用的战斗动作 =======================

MELEE_CONFIG = """
    target = "single"
    range = 3                              # 近战：3 米内
    visible = True
    noise = 30
    requires = {requires}
    check = best("strength", "agility")    # 力量（筋力）和敏捷都掷，取等级高的
    reactions = ["counter", "dodge"]       # 对方可以反击或闪避
    hit = level >= 1 and level >= opp_level   # 平手算打中（被反击时只造成一半伤害；闪避平手算闪开，由闪避作废）
"""

DODGE = preset(
    "闪避",
    "dodge",
    "被攻击时躲开：敏捷检定，等级不低于对方就闪开（平手算闪开）。",
    """
    target = "self"
    check = "agility"
    """,
    """
    if reacting and level >= 1 and level >= opp_level:
        self.negate()
    """,
)


def counter(damage: str) -> dict[str, Any]:
    return preset(
        "反击",
        "counter",
        "被近战攻击时迎击：力量（筋力）检定，等级高过对方就挡下这次攻击，并反过来打中对方；平手时对方打中、只造成一半伤害。",
        """
        target = "self"
        check = "strength"
        """,
        f"""
        if reacting and level >= 1 and level > opp_level:
            self.negate()
            target.damage({damage})
        """,
    )


def defense_group(dmg: str) -> dict[str, Any]:
    return group("defense", "应对", [counter(dmg), DODGE], reactions=True, effects=False)


PLUS_USE = use(
    "发动＋",
    "每天一次、持续 10 分钟：这个技能的等级 ×（1 + 0.5 × “+”的个数），由幸运决定成不成功。",
    """
    target = "self"
    requires = this.plus > 0
    check = "luck"
    hit = level >= 1
    cooldown = 1440
    """,
    "self.modify(this.level, this.level * (1 + 0.5 * this.plus), 10)",
)
KP_USE = use(
    "特殊效果",
    "（任意规则）把这个用法的效果写清楚，由 KP 读了以后裁定：引擎只记下“用了”，消耗和冷却照写在设置里的算。",
)
PLUS_COL = field(
    "plus",
    "＋",
    "number",
    choices=PLUS,
    required=False,
    initial="0",
    description="爆发力：每天一次可以让这个技能（或宝具这一次）的效果 ×(1 + 0.5 × 个数)，由幸运决定成不成功",
)

# ======================= 御主 =======================

MASTER_MELEE_DMG = "(dice(1, str) if str > 0 else 0) + (dice(1, weapon_db) if weapon_db > 0 else 0)"
NOT_MUGGLE = 'background != "普通人"'

COMMAND_SPELLS = preset(
    "令咒",
    "command_spell",
    "御主手上的三划令咒：每用一种用法消去一划。令咒用完之后，英灵就不必再听从御主了。",
    """
    target = "none"
    requires = command_spells >= 1
    noise = 5
    """,
    uses=[
        use(
            "绝对命令",
            "对自己的英灵下一道必须服从的命令（越具体越有效）；也可以让英灵做到平时做不到的一件事。效果由 KP 裁定。",
            script="self.sub(command_spells, 1)",
        ),
        use(
            "空间转移",
            "无视距离，把自己的英灵瞬间召到身边。",
            script="servant.teleport(self)\nself.sub(command_spells, 1)",
        ),
        use(
            "魔力灌注",
            "把令咒里的魔力灌给英灵：英灵的魔力补满。",
            script="servant.add(mp, servant.mp_max)\nself.sub(command_spells, 1)",
        ),
        use(
            "自害",
            "命令自己的英灵自尽。",
            script="servant.set(hp, 0)\nself.sub(command_spells, 1)",
        ),
    ],
)

MASTER = {
    "name": "master",
    "label": "御主",
    "appearance_field": "appearance",
    "fields": [
        field("appearance", "外观", "text", description="角色的外观"),
        field("can_fly", "飞行能力", "boolean", description="是否可以飞行"),
        field(
            "background",
            "出身",
            "text",
            choices=BACKGROUNDS,
            description="普通人没有魔力、不能用魔术（作为补偿多 2~4 点属性，英灵幸运 +1 级，由 KP 审核）；"
            "魔术师、人造人、魔术使、代行者各有自己的魔术体系，魔力倍数见规则书",
        ),
        field(
            "story",
            "来历",
            "text",
            required=False,
            description="你是谁、从哪来、为什么卷进这场战争、手里的圣遗物是什么来历。"
            "只有你和 KP 看得到；开场时 KP 按这里安排你的起点和线索",
        ),
        field(
            "hp",
            "生命值",
            "resource",
            "runtime",
            min="0",
            max="hp_max",
            initial="hp_max",
            per_minute="0.1 + con / 20",
            vital=True,
            description="生命值",
        ),
        field(
            "mp",
            "魔力值",
            "resource",
            "runtime",
            min="0",
            max="mp_max",
            initial="mp_max",
            # 在自己的据点（魔术工房）里休息时回复得快
            per_minute='(0.1 + ap / 20) * (3 if inside("据点") else 1)',
            description="魔力值。在自己的据点里回复速度是平时的 3 倍",
        ),
        field(
            "shield", "护盾值", "resource", "runtime", min="0", initial="0", description="护盾值"
        ),
        field(
            "command_spells",
            "令咒",
            "number",
            "runtime",
            min="0",
            max="3",
            initial="3",
            description="剩下几划令咒",
        ),
        field(
            "str", "力量", "number", min="-2", max="5", description="运动能力、近战格斗能力、力气"
        ),
        field(
            "agi",
            "敏捷",
            "number",
            min="-2",
            max="5",
            description="身体灵活性、回避攻击的能力、远程射击能力、隐藏技巧、小技巧等",
        ),
        field(
            "con",
            "体质",
            "number",
            min="-2",
            max="5",
            description="身体健康程度、直接关系HP和对毒素等的耐受能力",
        ),
        field(
            "int",
            "智力",
            "number",
            min="-2",
            max="5",
            description="记忆力、推理分析能力、魔力（符文、魔法道具等有明确技法传承的魔术）",
        ),
        field(
            "per",
            "感知",
            "number",
            min="-2",
            max="5",
            description="感官的敏锐度、对幻术的耐受能力、魔力（借助自然地脉或神灵力量的魔术）",
        ),
        field(
            "cha",
            "魅力",
            "number",
            min="-2",
            max="5",
            description="影响他人的能力、魔力（血缘性魔术、各种超能力）",
        ),
        field(
            "mp_mult",
            "魔力倍数",
            "number",
            min="1",
            max="30",
            required=False,
            initial="1",
            description="魔力回路的多少：正规魔术师 3~4，人造人 20~30，魔术使 2~3（由 KP 审核）",
        ),
        field(
            "weapon_db",
            "武器伤害骰",
            "number",
            min="0",
            max="12",
            description="近战武器的伤害骰面数（1d几），空手是 0；可以参考 COC，但不是越高越好",
        ),
        field(
            "weapon_mystic",
            "武器是魔术礼装",
            "boolean",
            required=False,
            description="普通的武器伤不到英灵；魔术礼装、附了魔的武器可以（由 KP 审核）",
        ),
        field("silenced", "沉默", "boolean", "runtime", initial="False", hidden=True),
    ],
    "derived": [
        derived("perception_radius", "感知半径", "50 + per * 10", "m"),
        derived("concealment", "匿踪系数", "1"),
        derived("move_speed", "移动速度", "80 + agi * 10", "m/min"),
        derived("fly_multiplier", "飞行速度系数", "1"),
        derived("fly_speed", "飞行速度", "fly_multiplier * move_speed", "m/min"),
        derived("hear_multiplier", "听力系数", "1"),
        derived("hear_distance", "听力范围", "(10 + per * 4) * hear_multiplier", "m"),
        derived("muggle", "普通人", f"0 if {NOT_MUGGLE} else 1"),
        derived("hp_max", "生命值上限", "30 + con * 4"),
        derived(
            "mp_max", "魔力值上限", "0 if muggle else (10 + (max(int, per) + cha) * 2) * mp_mult"
        ),
        derived("ap", "魔术能力", "0 if muggle else max(int, per, cha)"),
    ],
    "damage_taken": "",
    "stealth": "",
    "search": "1d20 + per",
    "on_death": code(
        """
        # 御主死了：英灵断了魔力供给，开始消散（有单独行动的按天数，否则 1d(幸运) 小时）
        if not servant.masterless:
            servant.set(masterless, 1)
            servant.set(remaining, servant.independent_minutes if servant.independent_minutes > 0 else dice(1, servant.luk) * 60)
        # 被英灵杀死的人：凶手回魔力，杀得越多收益越少
        if target.template == "servant":
            target.add(mp, lookup(kill_mp, target.kills))
            target.add(kills, 1)
        """
    ),
    "groups": [
        group(
            "magic",
            "魔术",
            [
                preset(
                    "攻击魔术",
                    "attack_magic",
                    "红色的闪电射向目标",
                    """
                    target = "single"
                    range = 100
                    visible = True
                    requires = not silenced
                    noise = range
                    check = "magecraft"
                    difficulty = floor(distance / 500)    # 远程：每 500 米难度加 1
                    reactions = ["dodge"]
                    """,
                    """
                    # 5MP = 1d(4+魔术能力) 伤害；每满 5MP 多一颗
                    target.damage(dice(max(1, floor(this.mp_spent / 5)), 4 + ap))
                    """,
                    when=NOT_MUGGLE,
                ),
                preset(
                    "治疗魔术",
                    "heal_magic",
                    "绿色的光晕包裹对方",
                    """
                    target = "single"
                    range = 100
                    visible = True
                    requires = not silenced
                    noise = range / 10
                    """,
                    """
                    # 每 1MP 回复 2 + 魔术能力/2 点生命值
                    target.add(hp, (2 + floor(ap / 2)) * this.mp_spent)
                    """,
                    when=NOT_MUGGLE,
                ),
                preset(
                    "防护魔术",
                    "shield_magic",
                    "半透明的防护罩罩住对方",
                    """
                    target = "single"
                    range = 100
                    visible = True
                    requires = not silenced
                    noise = range / 10
                    """,
                    """
                    # 每 1MP 加 5 + 魔术能力/2 点护盾，护盾持续的分钟数等于投入的 MP
                    target.add(shield, (5 + floor(ap / 2)) * this.mp_spent, this.mp_spent)
                    """,
                    when=NOT_MUGGLE,
                ),
                preset(
                    "警戒结界",
                    "alert_field",
                    "看不见的结界：任何实体闯入都会通知施术者",
                    """
                    target = "none"
                    range = 1
                    visible = False
                    requires = not silenced
                    placement = placement(radius=(50 + ap) * this.mp_spent, perceive=0, duration=this.mp_spent * 10, notify=True)
                    """,
                    when=NOT_MUGGLE,
                ),
                preset(
                    "补魔魔术",
                    "mp_regen_magic",
                    "没有视觉效果的魔术，把自己的魔力分给对方（给英灵时 1MP 换 2MP）",
                    """
                    target = "single"
                    range = 10
                    visible = True
                    requires = not silenced
                    """,
                    """
                    if target.template == "servant":
                        target.add(mp, 2 * this.mp_spent)
                    else:
                        target.add(mp, this.mp_spent)
                    """,
                    when=NOT_MUGGLE,
                ),
                preset(
                    "暗示",
                    "suggestion",
                    "对一个普通人下达命令。危险或复杂的命令由 KP 判定是否执行；检定失败时对方不受影响。",
                    """
                    target = "single"
                    range = 10
                    visible = True
                    requires = not silenced and target.template == "master" and target.muggle
                    check = "charisma"
                    """,
                    when=NOT_MUGGLE,
                ),
                preset(
                    "使魔",
                    "summon_familiar",
                    "放出小型使魔（鸟、猫、虫……）：每只 1MP，最多 3 + 魔术能力 只，存在一天。使魔和你共享知觉，只有 1 点生命值，攻击它的难度 +5。",
                    """
                    target = "none"
                    requires = not silenced and this.mp_spent <= 3 + ap
                    cast_time = 1
                    """,
                    'self.summon(familiar, this.mp_spent, 1440, appearance="一只不起眼的小动物", can_fly=True, per=ap)',
                    when=NOT_MUGGLE,
                ),
                preset(
                    "强化",
                    "reinforcement",
                    "（任意规则）强化一件物品或自己的身体：变得更坚固、更锋利、更快。效果按投入的魔力由 KP 裁定。",
                    when=NOT_MUGGLE,
                ),
            ],
            fields=[
                field(
                    "mp_spent",
                    "消耗魔力值",
                    "param",
                    min="1",
                    max="mp_max",
                    spends="mp",
                    description="这次投入多少魔力",
                ),
            ],
            damage_kind="magic",
            placements=True,
            max_count=None,
            use_templates=[KP_USE],
        ),
        group(
            "master_action",
            "御主行动",
            [
                COMMAND_SPELLS,
                preset(
                    "近战攻击",
                    "master_melee",
                    "徒手或用武器近身攻击。普通的武器伤不到英灵，魔术礼装可以。",
                    MELEE_CONFIG.format(requires="None"),
                    f"""
                    # 平手（被反击时）只造成一半伤害
                    half = opposed and level == opp_level
                    target.damage(({MASTER_MELEE_DMG}) / (2 if half else 1), "magic" if weapon_mystic else "mundane")
                    """,
                ),
                preset(
                    "设立据点",
                    "base",
                    "把自己所在的这栋建筑设为据点（魔术师叫它工房）：有人闯入时你会知道，在里面休息时魔力回复是平时的 3 倍。",
                    """
                    target = "none"
                    cast_time = 60
                    placement = placement(building=True, perceive=0.3, notify=True)
                    """,
                ),
                preset(
                    "补魔",
                    "mp_regen",
                    "普通人可以通过身体层面的亲密接触恢复英灵一半的魔力（请铺垫好坚实的剧情基础）",
                    """
                    target = "single"
                    range = 1
                    visible = True
                    cast_time = 120
                    cooldown = 1440
                    """,
                    """
                    # 每天一次，花 2 小时，恢复对方魔力上限的一半
                    target.add(mp, target.mp_max * 0.5)
                    """,
                    when=f"not ({NOT_MUGGLE})",
                ),
                preset(
                    "缔结契约",
                    "contract",
                    "和失去御主的英灵缔结契约（要有令咒）：英灵停止消散，成为你的英灵。",
                    """
                    target = "single"
                    range = 10
                    visible = True
                    requires = target.template == "servant" and target.masterless and command_spells >= 1
                    cast_time = 1
                    """,
                    """
                    target.set(masterless, 0)
                    target.set(remaining, 1)
                    """,
                ),
            ],
            placements=True,
            damage_kind="mundane",
        ),
        defense_group(MASTER_MELEE_DMG),
    ],
}

# ======================= 英灵 =======================

SERVANT_MELEE_DMG = 'dice(agi if klass == "Assassin" else str, lookup(class_melee, klass))'
# 日常耗魔（每天，按分钟扣）：基础 2；EX/A/B 级的技能各 4/2/1；开着的宝具各 1；狂战士再加狂化等级
_SKILLS = ("klass_skill", "personal_skill")
UPKEEP = (
    "(2"
    + "".join(
        f" + 4 * count({g}.level, 10) + 2 * count({g}.level, 5) + count({g}.level, 4)"
        for g in _SKILLS
    )
    + " + count(noble_phantasm.active, 1) + servant.madness.level) / 1440"
)
STEALTH = code(
    """
    max(
        (10 + min(servant.presence_concealment.level, 6) * ceil(max(distance, 1) / 40) if distance <= 200 else 999) if servant.presence_concealment.level > 0 else 0,
        999 if spirit_form and observer.template == "master" and observer.muggle else 0,
    )
    """
)
# 神秘：普通的攻击伤不到英灵；灵体化时只有魔力伤害碰得到；对魔力挡掉一部分魔力伤害
SERVANT_DAMAGE = code(
    """
    0 if kind == "mundane" or (spirit_form and kind != "magic") else max(0, amount - 5 * servant.anti_magic.level) if kind == "magic" else amount
    """
)
RANGED = """
    target = "single"
    range = 1000
    visible = True
    noise = 10
    requires = not spirit_form
    check = "{check}"
    difficulty = floor(distance / 500)    # 远程：每 500 米难度加 1
    reactions = ["dodge"]
"""
ATTRS = [("str", "筋力"), ("agi", "敏捷"), ("con", "耐久"), ("int", "魔力"), ("luk", "幸运")]


def attr_plus(name: str, label: str) -> dict[str, Any]:
    return preset(
        f"发动＋：{label}",
        f"plus_{name}",
        f"每天一次、持续 10 分钟：{label} ×（1 + 0.5 × “+”的个数），最高到 9；由幸运决定成不成功。",
        """
        target = "self"
        check = "luck"
        hit = level >= 1
        cooldown = 1440
        """,
        f"self.modify({name}, min(9, {name} * (1 + 0.5 * {name}_plus)), 10)",
        when=f"{name}_plus > 0",
    )


# 宝具的用法模板：玩家给自己的宝具加用法时可以照抄
NP_COST = "lookup(skill_cost, this.level) * lookup(np_cost, this.np_type)"
NP_DAMAGE = (
    "(dice(lookup(np_dice_count, this.level), lookup(np_dice_sides, this.level))"
    " + lookup(np_bonus, this.level)) * boost"
)


def beam(name: str, shape: str, desc: str) -> dict[str, Any]:
    return use(
        name,
        desc
        + " 只能闪避；100 米内对人、对军默认极难成功，对城、对界默认困难成功，更远时反过来。消耗：技能消耗（按宝具等级）× 类型倍数。",
        f"""
        target = "single"
        visible = True
        noise = 1000
        reveal = this.release
        requires = this.release and not spirit_form and mp >= cost
        reactions = ["dodge"]
        auto_level = ((3 if distance <= 100 else 2) if this.np_type == "对人" or this.np_type == "对军" else (2 if distance <= 100 else 3))
        {shape}
        """,
        f"""
        cost = {NP_COST}
        boost = 1 + 0.5 * this.plus * this.use_plus
        self.sub(mp, cost)
        target.damage({NP_DAMAGE})
        """,
    )


NP_TEMPLATES = [
    use(
        "当作武器",
        "不解放真名，只把宝具当成手里的武器：和英灵的近战攻击一样算，对方可以反击或闪避，不暴露宝具的名字。",
        MELEE_CONFIG.format(requires="not spirit_form") + "\n    reveal = False",
        f"""
        half = opposed and level == opp_level
        target.damage({SERVANT_MELEE_DMG} * (1 + 0.5 * this.plus * this.use_plus) / (2 if half else 1))
        """,
    ),
    beam("真名解放·对人", "", "解放真名，对一个人的必杀一击。"),
    beam(
        "真名解放·对军",
        "shape = capsule(length=200, width=20)",
        "解放真名，扫过一条 200 米长、20 米宽的范围，范围里的每个人各自闪避。",
    ),
    beam(
        "真名解放·对城",
        "shape = capsule(length=1000, width=80)",
        "解放真名，扫过一条 1 公里长、80 米宽的范围。",
    ),
    beam(
        "真名解放·对界",
        "shape = sphere(radius=500)",
        "解放真名，以瞄准的地方为中心、半径 500 米的一切。",
    ),
    use(
        "开关",
        "打开或关上宝具（例如隐藏武器的风之结界、封印自己的眼罩）：常驻效果写在宝具的修正里，用 this.active 判断开着没有；开着的宝具每天多耗 1 点魔力。",
        'target = "self"',
        """
        if this.active:
            self.set(this.active, 0)
        else:
            self.set(this.active, 1)
            self.sub(mp, lookup(skill_cost, this.level))
        """,
    ),
    use(
        "召唤",
        "解放真名，召唤宝具里的坐骑或军势：由你控制，存在 1 小时。要改数量、强弱就改脚本里的 rank 和 size。",
        """
        target = "none"
        noise = 300
        reveal = this.release
        requires = this.release and mp >= cost
        """,
        f"""
        cost = {NP_COST}
        self.sub(mp, cost)
        self.summon(squad, 1, 60, appearance="宝具召唤出的军势", can_fly=False, rank=this.level, size=10)
        """,
    ),
    use(
        "结界",
        "解放真名，展开一个结界（例如固有结界、吸取生命的血之神殿）：半径随宝具等级，持续 10 分钟，有人进出你会知道。结界里发生什么写在说明里，由 KP 裁定。",
        """
        target = "none"
        noise = 200
        reveal = this.release
        requires = this.release and mp >= cost
        placement = placement(radius=50 * this.level, perceive=1, duration=10, notify=True)
        """,
        f"""
        cost = {NP_COST}
        self.sub(mp, cost)
        """,
    ),
    KP_USE,
]

NP_FIELDS = [
    field("level", "等级", "number", choices=RANKS),
    field(
        "np_type",
        "类型",
        "text",
        choices=["对人", "对军", "对城", "对界"],
        description="决定解放真名时的范围和消耗倍数（对人 1、对军 3、对城 5、对界 10）",
    ),
    PLUS_COL,
    field(
        "active",
        "开着",
        "boolean",
        "runtime",
        required=False,
        description="可以开关的宝具开着没有（用“开关”这个用法切换）",
    ),
    field(
        "release",
        "解放真名",
        "param",
        choices=["不解放=0", "解放=1"],
        description="这次要不要解放真名：解放才能用宝具的全力，但附近的人会听到宝具的名字",
    ),
    field(
        "use_plus",
        "用＋",
        "param",
        choices=["不用=0", "用=1"],
        max="1 if this.plus > 0 else 0",
        check="luck",
        cooldown="1440",
        description="这次要不要用“+”：每天一次，由幸运决定成不成功",
    ),
]

SKILL_COLS = [field("level", "等级", "number", choices=RANKS), PLUS_COL]


def klass_skill(name: str, pid: str, desc: str, when: str, **kw: Any) -> dict[str, Any]:
    uses = kw.pop("uses", [])
    return preset(name, pid, desc, when=when, uses=[*uses, PLUS_USE], **kw)


MADNESS = [
    ("str", "str + (2 if this.level >= 5 else 1)"),
    ("con", "con + (1 if this.level >= 2 else 0)"),
    ("agi", "agi + (1 if this.level >= 3 else 0)"),
    ("int", "int + (1 if this.level >= 4 else -1 if this.level <= 2 else 0)"),
    ("luk", "luk - (1 if this.level == 1 else 0)"),
]
ATTR_DESC = [
    "决定近战攻击和近战物理伤害",
    "决定速度、远程物理伤害、闪避",
    "决定生命值",
    "决定魔力值、魔力豁免",
    "天意；幸运豁免、发动“+”、失去御主后还能存在多久",
]

SERVANT = {
    "name": "servant",
    "label": "英灵",
    "appearance_field": "appearance",
    "fields": [
        field("appearance", "外观", "text", description="别人看到的样子（不要写出真名）"),
        field(
            "true_name",
            "真名",
            "text",
            description="英灵的真名：别人只知道你的职阶，真名暴露了，弱点和传说也就跟着暴露了",
        ),
        field("can_fly", "飞行能力", "boolean", description="是否可以飞行"),
        field(
            "hp",
            "生命值",
            "resource",
            "runtime",
            min="0",
            max="hp_max",
            initial="hp_max",
            per_minute="hp_max * 0.05 * lookup(class_heal, klass)",
            vital=True,
            description="生命值",
        ),
        field(
            "mp",
            "魔力值",
            "resource",
            "runtime",
            min="0",
            max="mp_max",
            initial="mp_max",
            # 日常消耗按分钟扣；Caster 在自己的阵地里每分钟回复阵地作成等级点
            per_minute=f'-{UPKEEP} + (servant.territory.level if inside("阵地作成") else 0)',
            vital=True,
            description="魔力值。每天的日常消耗按分钟扣：基础 2，加上 EX/A/B 级技能各 4/2/1，开着的宝具各 1；降到 0 会消失",
        ),
        field(
            "shield", "护盾值", "resource", "runtime", min="0", initial="0", description="护盾值"
        ),
        field("klass", "职阶", "text", choices=CLASSES, description="英灵的职阶，别人只知道这个"),
        *[
            field(n, label, "number", choices=RANKS, description=desc)
            for (n, label), desc in zip(ATTRS, ATTR_DESC, strict=True)
        ],
        field(
            "np",
            "宝具",
            "number",
            choices=RANKS,
            description="参数表上的宝具等级（主要宝具的等级；每个宝具在宝具栏里各有自己的等级）",
        ),
        *[
            field(
                f"{n}_plus",
                f"{label}＋",
                "number",
                choices=PLUS,
                required=False,
                initial="0",
                description=f"{label}的爆发力：每天一次，10 分钟内 {label} ×(1 + 0.5 × 个数)",
            )
            for n, label in ATTRS
        ],
        field("spirit_form", "灵体化中", "boolean", "runtime", initial="False"),
        field("riding", "骑乘中", "boolean", "runtime", initial="False"),
        field("masterless", "失去御主", "boolean", "runtime", initial="False"),
        field(
            "remaining",
            "失去御主后的剩余时间",
            "number",
            "runtime",
            min="0",
            initial="1",
            unit="min",
            per_minute="-1 if masterless else 0",
            vital=True,
            description="失去御主后按分钟倒数，到 0 消散；重新缔结契约后停止",
        ),
        field(
            "kills",
            "杀人数",
            "number",
            "runtime",
            min="0",
            initial="0",
            hidden=True,
            description="靠杀人回魔力时，杀得越多收益越少",
        ),
    ],
    "derived": [
        derived("perception_radius", "感知半径", "150 + 30 * max(agi, int)", "m"),
        derived("concealment", "匿踪系数", "1"),
        derived("move_speed", "移动速度", "(3 + lookup(class_speed, klass)) * agi * 60", "m/min"),
        derived("fly_multiplier", "飞行速度系数", "4"),
        derived("fly_speed", "飞行速度", "fly_multiplier * move_speed", "m/min"),
        derived("hear_multiplier", "听力系数", "3"),
        derived("hear_distance", "听力范围", "(10 + agi * 4) * hear_multiplier", "m"),
        derived("hp_max", "生命值上限", "con * lookup(class_hp, klass)"),
        derived("mp_max", "魔力值上限", "int * 30"),
        derived(
            "independent_minutes",
            "单独行动",
            "lookup(independent_days, servant.independent_action.level) * 1440"
            " if servant.independent_action.level > 0 else 0",
            "min",
        ),
    ],
    "damage_taken": SERVANT_DAMAGE,
    "stealth": STEALTH,
    "search": "1d20 + int + agi",
    "on_death": "",
    "groups": [
        group(
            "servant_action",
            "英灵动作",
            [
                preset(
                    "灵体化",
                    "spirit",
                    "进入或解除灵体化：普通人看不见，物理攻击碰不到你，你也不能攻击，速度提升 30%；英灵和魔术师照样感觉得到你。不消耗魔力。",
                    """
                    target = "self"
                    """,
                    """
                    self.set(spirit_form, 0 if spirit_form else 1)
                    if not spirit_form:
                        self.set(riding, 0)
                    """,
                    effects=[
                        effect(
                            "灵体化时速度提升 30%",
                            "move_speed",
                            "move_speed * 1.3 if spirit_form else move_speed",
                        )
                    ],
                ),
                preset(
                    "近战攻击",
                    "servant_melee_attack",
                    "英灵的近战攻击：伤害 (筋力)d(职阶伤害骰)；刺客是 (敏捷)d6，对方没发现时 d12",
                    MELEE_CONFIG.format(requires="not spirit_form"),
                    """
                    x = agi if klass == "Assassin" else str
                    y = 12 if klass == "Assassin" and unseen else lookup(class_melee, klass)
                    # 平手（被反击时）只造成一半伤害
                    half = opposed and level == opp_level
                    target.damage(dice(x, y) / (2 if half else 1))
                    """,
                ),
                preset(
                    "远程攻击",
                    "servant_range_attack",
                    "英灵的远程攻击：敏捷 + 1d(职阶伤害骰)",
                    RANGED.format(check="agility"),
                    "target.damage(agi + dice(1, lookup(class_melee, klass)))",
                    when='klass != "Archer" and klass != "Caster"',
                ),
                preset(
                    "Archer远程攻击",
                    "archer_range_attack",
                    "Archer 的远程攻击：(敏捷)d8",
                    RANGED.format(check="agility"),
                    "target.damage(dice(agi, lookup(class_melee, klass)))",
                    when='klass == "Archer"',
                ),
                *[attr_plus(n, label) for n, label in ATTRS],
            ],
            hidden=True,
        ),
        group(
            "klass_skill",
            "职阶技能",
            [
                klass_skill(
                    "骑乘",
                    "ride",
                    "骑上或跳下坐骑：骑乘时速度 + 骑乘等级 × 5 米/秒。灵体化时不能骑乘。骑上时按技能等级消耗魔力。参考：Rider 上升 3 级、Saber 上升 1 级。",
                    is_class("Rider", "Saber"),
                    config="""
                    target = "self"
                    requires = not spirit_form
                    """,
                    script="""
                    if not riding:
                        self.sub(mp, lookup(skill_cost, this.level))
                    self.set(riding, 0 if riding else 1)
                    """,
                    effects=[
                        effect(
                            "骑乘时速度 + 骑乘等级 × 5 米/秒",
                            "move_speed",
                            "move_speed + this.level * 300 if riding else move_speed",
                        )
                    ],
                ),
                klass_skill(
                    "对魔力",
                    "anti_magic",
                    "受到魔力伤害（魔术、魔术攻击）时，无视其中 5/10/15/20/25 点（E~A），EX 为 50 点。宝具伤害不算魔力伤害。参考：Saber 上升 3 级、Lancer 2 级、Archer 和 Rider 1 级。",
                    is_class("Saber", "Archer", "Lancer", "Rider"),
                ),
                klass_skill(
                    "单独行动",
                    "independent_action",
                    "没有御主也能存在 1/3/6/10/15 天（E~A，EX 30 天）。参考：等级为耐久和魔力中较高的一个。",
                    is_class("Archer"),
                ),
                klass_skill(
                    "气息遮蔽",
                    "presence_concealment",
                    "隐藏自己的气息：别人发现你要掷出 10 + 等级 × ⌈距离÷40 米⌉（EX 按 6 算）；200 米外发现不了。"
                    "御主用 1d20+感知，英灵用 1d20+魔力+敏捷。攻击会暴露给对象；对方没发现你时，近战伤害骰变成 d12，对方也躲不开。参考：等级为敏捷。",
                    is_class("Assassin"),
                ),
                klass_skill(
                    "阵地作成",
                    "territory",
                    "花一天布置自己的阵地：以自己为中心画一个圆，或者把自己所在的整栋建筑做成阵地。有人闯入时你会知道；"
                    "在阵地里每分钟额外回复等级点魔力。参考：等级为魔力，有布阵的事迹再 +1 级。",
                    is_class("Caster"),
                    uses=[
                        use(
                            "圆形阵地",
                            "以自己为中心、半径 125 米的阵地。",
                            """
                            target = "none"
                            cast_time = 1440
                            placement = placement(radius=125, perceive=0.2, notify=True)
                            """,
                        ),
                        use(
                            "建筑阵地",
                            "把自己所在的整栋建筑做成阵地，不论多大。",
                            """
                            target = "none"
                            cast_time = 1440
                            placement = placement(building=True, perceive=0.2, notify=True)
                            """,
                        ),
                    ],
                ),
                klass_skill(
                    "道具作成",
                    "item_construction",
                    "（任意规则）制作魔术道具：花时间和魔力，做出符合自己传说的道具。做出什么、效果多强由 KP 按等级裁定。",
                    is_class("Caster"),
                    uses=[
                        use(
                            "制作道具",
                            "花一小时做一件魔术道具，消耗技能等级的魔力；做出什么由 KP 裁定。",
                            """
                            target = "none"
                            cast_time = 60
                            """,
                            "self.sub(mp, lookup(skill_cost, this.level))",
                        )
                    ],
                ),
                klass_skill(
                    "狂化",
                    "madness",
                    "以理性为代价提升能力：E 力量 +1 级、幸运和魔力 -1 级；D 力量和耐久 +1 级、魔力 -1 级；C 力量、耐久、敏捷 +1 级；"
                    "B 力量、耐久、敏捷、魔力 +1 级；A 力量 +2 级，耐久、敏捷、魔力 +1 级。等级越高越难沟通，C 以上几乎不能说话。"
                    "每天的魔力消耗多出狂化等级点。等级由御主决定。",
                    is_class("Berserker"),
                    effects=[effect(f"狂化：{n}", n, formula) for n, formula in MADNESS],
                ),
            ],
            fields=SKILL_COLS,
            placements=True,
            use_templates=[PLUS_USE, KP_USE],
        ),
        group(
            "personal_skill",
            "保有技能",
            [],
            fields=SKILL_COLS,
            max_count=None,
            placements=True,
            use_templates=[PLUS_USE, KP_USE],
        ),
        group(
            "servant_magic",
            "英灵魔术",
            [
                preset(
                    "Caster远程魔术",
                    "caster_magic_attack",
                    "Caster 的魔术攻击：(魔力)d4 的魔力伤害",
                    RANGED.format(check="intelligence"),
                    "target.damage(dice(int, lookup(class_melee, klass)))",
                    when='klass == "Caster"',
                ),
                preset(
                    "咏唱攻击魔术",
                    "caster_chant",
                    "咏唱的攻击魔术：每 3MP 一小节，造成 1d4 魔力伤害，最多 15 小节。",
                    """
                    target = "single"
                    range = 1000
                    visible = True
                    noise = 100
                    requires = not spirit_form and this.mp_spent <= 45
                    check = "intelligence"
                    difficulty = floor(distance / 500)
                    reactions = ["dodge"]
                    """,
                    "target.damage(dice(max(1, floor(this.mp_spent / 3)), 4))",
                    when='klass == "Caster"',
                ),
                preset(
                    "治疗",
                    "caster_heal",
                    "支付魔力恢复一个单位的生命值：1MP 恢复 10HP。",
                    """
                    target = "single"
                    range = 25
                    visible = True
                    noise = 10
                    """,
                    "target.add(hp, 10 * this.mp_spent)",
                    when='klass == "Caster"',
                ),
                preset(
                    "防护魔术",
                    "caster_shield",
                    "为一个单位制造防护罩：每 1MP 获得 10 点护盾，最多持续 3 小时。",
                    """
                    target = "single"
                    range = 25
                    visible = True
                    noise = 10
                    """,
                    "target.add(shield, 10 * this.mp_spent, 180)",
                    when='klass == "Caster"',
                ),
                preset(
                    "暗示",
                    "caster_suggestion",
                    "对普通人下达的命令必定被执行；对魔术师下达命令要做魔力检定，危险或复杂的命令由 KP 判定难度。",
                    """
                    target = "single"
                    range = 25
                    visible = True
                    requires = target.template == "master"
                    check = "intelligence"
                    hit = target.muggle or level >= 1    # 对普通人必定生效
                    """,
                    when='klass == "Caster"',
                ),
                preset(
                    "警戒结界",
                    "caster_alert",
                    "花 3 分钟布置一个半径 250 米的结界，任何实体闯入都会通知你。",
                    """
                    target = "none"
                    range = 1
                    cast_time = 3
                    placement = placement(radius=250, perceive=0, notify=True)
                    """,
                    when='klass == "Caster"',
                ),
                preset(
                    "使魔",
                    "caster_familiar",
                    "放出 10 只使魔：和你共享知觉，能瞬间移动，只有 1 点生命值，攻击它的难度 +5。存在一天，消耗 5MP。",
                    """
                    target = "none"
                    requires = mp >= 5
                    cast_time = 1
                    """,
                    """
                    self.sub(mp, 5)
                    self.summon(familiar, 10, 1440, appearance="Caster 的使魔", can_fly=True, per=int)
                    """,
                    when='klass == "Caster"',
                ),
                preset(
                    "傀儡兵",
                    "caster_puppets",
                    "叫出一队傀儡兵：每个兵消耗 5MP，最多 5 × 魔力 个；全部能力等于魔力 - 2 级（至少 E），存在一天，由你指挥。",
                    """
                    target = "none"
                    requires = this.mp_spent >= 5 and this.mp_spent <= 25 * int
                    cast_time = 1
                    """,
                    'self.summon(squad, 1, 1440, appearance="一队傀儡兵", can_fly=False, rank=max(1, int - 2), size=floor(this.mp_spent / 5))',
                    when='klass == "Caster"',
                ),
                preset(
                    "飞行",
                    "caster_flight",
                    "飞在空中：每 5MP 飞 1 分钟。",
                    """
                    target = "self"
                    requires = this.mp_spent >= 5
                    noise = 20
                    """,
                    "self.modify(can_fly, 1, this.mp_spent / 5)",
                    when='klass == "Caster"',
                ),
                preset(
                    "瞬间移动",
                    "caster_blink",
                    "（任意规则）花一个动作瞬间出现在别处：每 1MP 移动 5 米。移到哪里由 KP 按距离裁定。",
                    'target = "none"',
                    when='klass == "Caster"',
                ),
                preset(
                    "强化",
                    "caster_enhance",
                    "（任意规则）把一件物品升级为宝具，等级为魔力 - 1 级。效果由 KP 裁定。",
                    'target = "none"\ncast_time = 10',
                    when='klass == "Caster"',
                ),
            ],
            fields=[
                field(
                    "mp_spent",
                    "消耗魔力值",
                    "param",
                    min="0",
                    max="mp_max",
                    spends="mp",
                    description="这次投入多少魔力（不需要魔力的填 0）",
                ),
            ],
            damage_kind="magic",
            placements=True,
            hidden=True,
        ),
        group(
            "noble_phantasm",
            "宝具",
            [],
            fields=NP_FIELDS,
            damage_kind="noble_phantasm",
            max_count=None,
            placements=True,
            shapes=["capsule", "sphere", "cone"],
            use_templates=NP_TEMPLATES,
        ),
        defense_group(SERVANT_MELEE_DMG),
    ],
}

# ======================= 召唤物 =======================

FAMILIAR = {
    "name": "familiar",
    "label": "使魔",
    "appearance_field": "appearance",
    "fields": [
        field("appearance", "外观", "text"),
        field("can_fly", "飞行能力", "boolean"),
        field("per", "感知", "number", description="使魔的感官（召唤时按主人的能力定）"),
        field("hp", "生命值", "resource", "runtime", min="0", max="1", initial="1", vital=True),
    ],
    "derived": [
        derived("perception_radius", "感知半径", "30 + per * 10", "m"),
        derived("concealment", "匿踪系数", "0.3"),
        derived("move_speed", "移动速度", "300", "m/min"),
        derived("fly_multiplier", "飞行速度系数", "2"),
        derived("fly_speed", "飞行速度", "fly_multiplier * move_speed", "m/min"),
        derived("hear_multiplier", "听力系数", "1"),
        derived("hear_distance", "听力范围", "(10 + per * 4) * hear_multiplier", "m"),
        derived("agi", "敏捷", "per"),
    ],
    "damage_taken": "",
    "stealth": "",
    "search": "1d20 + per",
    "on_death": "",
    "groups": [group("defense", "应对", [DODGE], reactions=True, effects=False)],
}

SQUAD_DMG = "dice(rank, 6) + troops"
SQUAD = {
    "name": "squad",
    "label": "召唤兵团",
    "appearance_field": "appearance",
    "fields": [
        field("appearance", "外观", "text"),
        field("can_fly", "飞行能力", "boolean"),
        field("rank", "等级", "number", choices=RANKS, description="每个兵的全部能力等级"),
        field("size", "人数", "number", min="1", description="召唤时有几个兵"),
        field(
            "hp",
            "生命值",
            "resource",
            "runtime",
            min="0",
            max="hp_max",
            initial="hp_max",
            vital=True,
            description="全队的生命值：每个兵 等级 × 10 点，打掉的折算成减员",
        ),
        field(
            "shield", "护盾值", "resource", "runtime", min="0", initial="0", description="护盾值"
        ),
    ],
    "derived": [
        derived("perception_radius", "感知半径", "100 + rank * 10", "m"),
        derived("concealment", "匿踪系数", "1"),
        derived("move_speed", "移动速度", "(3 + 6) * rank * 60", "m/min"),
        derived("fly_multiplier", "飞行速度系数", "4"),
        derived("fly_speed", "飞行速度", "fly_multiplier * move_speed", "m/min"),
        derived("hear_multiplier", "听力系数", "1"),
        derived("hear_distance", "听力范围", "(10 + rank * 4) * hear_multiplier", "m"),
        derived("hp_max", "生命值上限", "size * rank * 10"),
        derived("troops", "还剩几个兵", "ceil(hp / (rank * 10))"),
        derived("str", "筋力", "rank"),
        derived("agi", "敏捷", "rank"),
    ],
    # 召唤出来的神秘：普通的攻击伤不到
    "damage_taken": '0 if kind == "mundane" else amount',
    "stealth": "",
    "search": "1d20 + rank",
    "on_death": "",
    "groups": [
        group(
            "squad_action",
            "兵团行动",
            [
                preset(
                    "围攻",
                    "squad_attack",
                    "整队一起扑上去：伤害 (等级)d6 + 剩下的人数。",
                    MELEE_CONFIG.format(requires="None"),
                    f"""
                    half = opposed and level == opp_level
                    target.damage(({SQUAD_DMG}) / (2 if half else 1))
                    """,
                )
            ],
            hidden=True,
        ),
        defense_group(SQUAD_DMG),
    ],
}

TABLES = [
    table("class_hp", by_class([16, 14, 14, 14, 10, 12, 18])),
    table("class_melee", by_class([10, 8, 10, 10, 4, 6, 12])),
    table("class_speed", by_class([6, 8, 7, 9, 5, 8, 6])),
    table("class_heal", by_class([1, 1, 1.1, 1, 1.2, 0.9, 1.3])),
    # 技能施放的魔力：E~A 1~5，EX 8
    table("skill_cost", by_rank([1, 2, 3, 4, 5, 8]), kind="range"),
    table("np_cost", [("对人", 1), ("对军", 3), ("对城", 5), ("对界", 10)]),
    table("np_dice_count", by_rank([3, 3, 4, 5, 5, 6]), kind="range"),
    table("np_dice_sides", by_rank([6, 10, 10, 10, 12, 12]), kind="range"),
    table("np_bonus", by_rank([1, 3, 5, 7, 9, 15]), kind="range"),
    # 豁免的修正：E~A -4/-2/0/+2/+4，EX +8
    table("save_mod", by_rank([-4, -2, 0, 2, 4, 8]), kind="range"),
    # 单独行动：没有御主也能存在的天数
    table("independent_days", by_rank([1, 3, 6, 10, 15, 30]), kind="range"),
    # 杀人回魔：杀了几个人以后，再杀一个回多少
    table("kill_mp", [(0, 5), (10, 4), (30, 3), (60, 2), (100, 1)], kind="range"),
]

CHECKS = [
    check("strength", "力量 / 筋力", "1d20 + str"),
    check("agility", "敏捷", "1d20 + agi"),
    check("constitution", "体质 / 耐久", "1d20 + con"),
    check("intelligence", "智力 / 魔力", "1d20 + int"),
    check("perception", "感知", "1d20 + per"),
    check("charisma", "魅力", "1d20 + cha"),
    check("luck", "幸运", "1d20 + luk"),
    check("magecraft", "魔术", "1d20 + ap"),
    # 宝具特效的豁免：对 10 + 宝具等级（技能设置里 difficulty 写宝具等级）
    check(
        "magic_save",
        "魔力豁免",
        '1d20 + (lookup(save_mod, int) if self.template == "servant" else int)',
    ),
    check(
        "luck_save",
        "幸运豁免",
        '1d20 + (lookup(save_mod, luk) if self.template == "servant" else 0)',
    ),
]

RULES_TEXT = code(
    """
    引擎已经执行的规则（检定、对抗、伤害、神秘、魔力、隐匿、令咒、召唤、阵地、死亡）不用 KP 再算。下面这些由 KP 按型月的设定处理：

    1. 真名：英灵对外只以职阶相称。宝具平时当武器用不会暴露名字；解放真名时附近的人会听到宝具的名字（引擎通知），
       知道宝具名字的人可以推出英灵的真名、传说和弱点。御主看到别的英灵时，看得到它的职阶和六项参数，看不到真名、技能和宝具。
    2. 神秘的隐匿：魔术和英灵的存在要对普通人保密；在普通人面前大打出手、留下痕迹会招来监督者和其他御主的注意。
    3. 通讯：御主和英灵之间可以用念话交流，不受距离限制。任何一方进入战斗，另一方没有别的观测手段时，视作双方共感、同时进入战斗状态。战斗中不准和队友交流。
    4. 令咒的“绝对命令”：命令越具体越有效（“立刻撤退”比“永远服从我”强）；也可以让英灵做到平时做不到的一件事（例如瞬间跨越很远的距离、在必死的一击下活下来）。
       令咒用完以后，英灵不必再服从御主；英灵可能因此背叛。
    5. 宝具和保有技能：玩家可以自己设计，须经过 KP 审核。用法里写成“任意规则”的（只有说明、没有设置和脚本），由 KP 按说明裁定效果；
       宝具特效需要对抗魔力或幸运时，技能设置写 save = "magic_save" 或 "luck_save"，difficulty 写 10 + 宝具等级。其他特效依照 Fate 原作的宝具效果比对。
    6. 结界宝具（例如固有结界）：结界里发生什么按宝具的说明裁定；引擎负责范围、持续时间和进出的通知。
    7. 狂化：等级越高越难沟通，C 以上几乎不能说话；狂化的英灵用技能和宝具时，复杂的用法由 KP 判断能不能做到。
    8. 暗示、强化、瞬间移动、道具作成等写成“任意规则”的魔术，叙事效果由 KP 裁定；写在设置和脚本里的消耗照常扣。
    """
)

# 示例：一个剑士和她的两件宝具（演示宝具的几种用法）
SAMPLE_NP = {
    "name": "誓约的胜利之剑",
    "id": "",
    "description": "被看不见的风包裹着的圣剑。平时用风藏起剑身，解放真名时放出光的洪流。",
    "fields": {"level": 5, "np_type": "对城", "plus": 0},
    "effects": [],
    # 宝具自己的设置是所有用法共用的：平时不暴露名字，解放真名时才喊出来
    "config": "reveal = this.release",
    "script": "",
    "uses": [NP_TEMPLATES[0], NP_TEMPLATES[3]],
}
SAMPLE_WIND = {
    "name": "风王结界",
    "id": "",
    "description": "把武器包裹在风里，让人看不出它的长短和形状：开着的时候近战更难应对。",
    "fields": {"level": 3, "np_type": "对人", "plus": 0},
    "effects": [
        {
            "description": "开着的时候筋力像高一级",
            "target": "str",
            "formula": "str + 1 if this.active else str",
            "priority": 1,
        }
    ],
    "config": "reveal = False",
    "script": "",
    "uses": [NP_TEMPLATES[5]],
}

PACK = {
    "world": {
        "name": "圣杯战争",
        "description": "以 Fate 系列的圣杯战争为基础，设定以原作为准。\n"
        "七名御主召唤七骑英灵，为了能实现一切愿望的圣杯互相厮杀。\n"
        "基调：严肃、紧张的异能战斗，伴随阴谋与背叛。死亡是真实的，没有复活。",
        "canon": "Type-Moon 圣杯战争",
        "reference_sites": ["https://www.tmdict.com/zh/"],
    },
    "templates": [MASTER, SERVANT, FAMILIAR, SQUAD],
    "player_entities": [
        {"template": "master", "min": 1, "max": 1},
        {"template": "servant", "min": 1, "max": 1},
    ],
    "formulas": [],
    "tables": TABLES,
    "checks": CHECKS,
    "rules_text": RULES_TEXT,
    "samples": [
        {
            "name": "示例御主",
            "template": "master",
            "sheet": {
                "name": "示例御主",
                "fields": {
                    "appearance": "穿红色外套的少女，双马尾",
                    "background": "魔术师",
                    "can_fly": False,
                    "str": 0,
                    "agi": 1,
                    "con": 1,
                    "int": 4,
                    "per": 2,
                    "cha": 2,
                    "mp_mult": 3,
                    "weapon_db": 0,
                    "weapon_mystic": False,
                },
            },
            "expected": {"hp_max": 34, "mp_max": 66, "ap": 4, "perception_radius": 70},
        },
        {
            "name": "示例英灵",
            "template": "servant",
            "sheet": {
                "name": "Saber",
                "fields": {
                    "appearance": "身穿蓝银铠甲、手持看不见的剑的少女骑士",
                    "true_name": "（示例）亚瑟王",
                    "can_fly": False,
                    "klass": "Saber",
                    "str": 5,
                    "agi": 3,
                    "con": 4,
                    "int": 2,
                    "luk": 4,
                    "np": 5,
                },
                "groups": {"noble_phantasm": [SAMPLE_NP, SAMPLE_WIND]},
                "preset_fields": {
                    "klass_skill": {"骑乘": {"level": 2}, "对魔力": {"level": 5}},
                },
            },
            "expected": {
                "hp_max": 64,
                "mp_max": 60,
                "move_speed": 1620,
                "perception_radius": 240,
                "independent_minutes": 0,
            },
        },
        {
            "name": "示例使魔",
            "template": "familiar",
            "sheet": {
                "name": "使魔",
                "fields": {"appearance": "一只乌鸦", "can_fly": True, "per": 3},
            },
            "expected": {"perception_radius": 60},
        },
        {
            "name": "示例兵团",
            "template": "squad",
            "sheet": {
                "name": "傀儡兵",
                "fields": {"appearance": "一队骷髅兵", "can_fly": False, "rank": 3, "size": 10},
            },
            "expected": {"hp_max": 300, "troops": 10},
        },
    ],
}


def main() -> int:
    sys.path.insert(0, str(ROOT))
    from smartkeeper.contracts import RulePack
    from smartkeeper.rules import RulesService
    from smartkeeper.rules.store import export_pack

    pack = RulePack.model_validate(PACK)
    problems = RulesService().validate_pack(pack)
    for p in problems:
        print(p.code, p.path, p.params)
    OUT.write_text(export_pack(pack) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT)}; {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
