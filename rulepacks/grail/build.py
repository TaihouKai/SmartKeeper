"""圣杯战争规则包：按规则书（docs 之外的本人规则书 v2026，2026-11-25 更新版）写成引擎的规则包。

    uv run python rulepacks/grail/build.py      # 写出 rulepacks/grail/pack.json（导入格式）并校验

规则书里引擎直接执行的部分都在这里；交给 KP 的部分写在 RULES_TEXT 里。
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
LEVELS = '["失败", "成功", "困难成功", "极难成功"]'

# 三档：>10 成功、>15 困难成功、>20 极难成功（难度加在需要的点数上）；英灵对人类至少困难成功
TIERS = (
    "level = max(\n"
    "    0 if roll - difficulty <= 10 else 1 if roll - difficulty <= 15 "
    "else 2 if roll - difficulty <= 20 else 3,\n"
    '    2 if self.template == "servant" and opponent.template == "master" else 0,\n'
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
    }


def group(name: str, label: str, presets: list[dict[str, Any]], **kw: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "name": name,
        "label": label,
        "fields": kw.pop("fields", []),
        "presets": presets,
        "min_count": 0,
        "max_count": kw.pop("max_count", 0),
        "effects": kw.pop("effects", True),
        "shapes": {"allowed": []},
        "hidden": kw.pop("hidden", False),
        "placements": kw.pop("placements", False),
        "timing": kw.pop("timing", True),
        "reactions": kw.pop("reactions", False),
        "damage_kind": kw.pop("damage_kind", ""),
    }
    out.update(kw)
    return out


def table(name: str, rows: list[tuple[Any, float]], kind: str = "exact") -> dict[str, Any]:
    return {"name": name, "kind": kind, "rows": [list(r) for r in rows]}


def by_class(values: list[float]) -> list[tuple[Any, float]]:
    return list(zip(CLASSES, values, strict=True))


def by_rank(values: list[float]) -> list[tuple[Any, float]]:
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
    check = best("strength", "agility")    # 筋力（力量）和敏捷都掷，取等级高的
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


# ======================= 御主 =======================

MASTER_MELEE_DMG = "(dice(1, str) if str > 0 else 0) + (dice(1, weapon_db) if weapon_db > 0 else 0)"

MASTER = {
    "name": "master",
    "label": "御主",
    "appearance_field": "appearance",
    "fields": [
        field("appearance", "外观", "text", description="角色的外观"),
        field("can_fly", "飞行能力", "boolean", description="是否可以飞行"),
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
            per_minute="0.1 + ap / 20",
            description="魔力值",
        ),
        field(
            "shield", "护盾值", "resource", "runtime", min="0", initial="0", description="护盾值"
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
            "weapon_db",
            "武器伤害骰",
            "number",
            min="0",
            max="12",
            description="近战武器的伤害骰面数（1d几），空手是 0；可以参考 COC，但不是越高越好",
        ),
        field(
            "is_muggle",
            "是否是普通人",
            "boolean",
            description="普通人（麻瓜）：没有魔力，不能用魔术",
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
        derived("hp_max", "生命值上限", "30 + con * 4"),
        derived("mp_max", "魔力值上限", "0 if is_muggle else 10 + (max(int, per) + cha) * 2"),
        derived("ap", "魔术能力", "0 if is_muggle else max(int, per, cha)"),
    ],
    "damage_taken": "",
    "stealth": "",
    "search": "1d20 + per",
    "on_death": code(
        """
        # 御主死了：英灵断了魔力供给，开始消散（有单独行动的按天数，否则 1d(幸运) 小时）
        if servant.masterless == 0:
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
                    target.damage(dice(
                        max(1, floor(this.mp_spent / 5)),
                        4 + ap
                    ))
                    """,
                    when="not is_muggle",
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
                    when="not is_muggle",
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
                    when="not is_muggle",
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
                    """
                    # 被触发时什么都不做，只通知施术者
                    pass
                    """,
                    when="not is_muggle",
                ),
                preset(
                    "补魔魔术",
                    "mp_regen_magic",
                    "没有视觉效果的魔术，把自己的魔力分给对方",
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
                    when="not is_muggle",
                ),
                preset(
                    "暗示",
                    "suggestion",
                    "对一个普通人下达命令。危险或复杂的命令由 KP 判定是否执行；检定失败时对方不受影响。",
                    """
                    target = "single"
                    range = 10
                    visible = True
                    requires = not silenced and target.template == "master" and target.is_muggle
                    check = "charisma"
                    """,
                    """
                    # 效果由 KP 按命令叙述；技能只判定成不成功
                    pass
                    """,
                    when="not is_muggle",
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
        ),
        group(
            "master_action",
            "御主行动",
            [
                preset(
                    "近战攻击",
                    "master_melee",
                    "徒手或用武器近身攻击",
                    MELEE_CONFIG.format(requires="None"),
                    f"""
                    # 平手（被反击时）只造成一半伤害
                    half = opposed and level == opp_level
                    target.damage(({MASTER_MELEE_DMG}) / (2 if half else 1))
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
                    when="is_muggle",
                ),
                preset(
                    "缔结契约",
                    "contract",
                    "和失去御主的英灵缔结契约：英灵停止消散。",
                    """
                    target = "single"
                    range = 10
                    visible = True
                    requires = target.template == "servant" and target.masterless == 1
                    cast_time = 1
                    """,
                    """
                    target.set(masterless, 0)
                    target.set(remaining, 1)
                    """,
                ),
            ],
        ),
        defense_group(MASTER_MELEE_DMG),
    ],
}

# ======================= 英灵 =======================

SERVANT_MELEE_DMG = 'dice(agi if klass == "Assassin" else str, lookup(class_melee, klass))'
UPKEEP = (
    "(2 + 4 * (count(klass_skill.level, 10) + count(personal_skill.level, 10))"
    " + 2 * (count(klass_skill.level, 5) + count(personal_skill.level, 5))"
    " + count(klass_skill.level, 4) + count(personal_skill.level, 4)) / 1440"
)
STEALTH = code(
    """
    max(
        (10 + min(servant.presence_concealment.level, 6) * ceil(max(distance, 1) / 40) if distance <= 200 else 999) if servant.presence_concealment.level > 0 else 0,
        999 if spirit_form and observer.template == "master" and observer.is_muggle else 0,
    )
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

SERVANT = {
    "name": "servant",
    "label": "英灵",
    "appearance_field": "appearance",
    "fields": [
        field("appearance", "外观", "text", description="角色的外观"),
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
            per_minute=f"-{UPKEEP}",
            vital=True,
            description="魔力值。每天的日常消耗按分钟扣：基础 2，加上 EX/A/B 级技能各 4/2/1。降到 0 会消失",
        ),
        field(
            "shield", "护盾值", "resource", "runtime", min="0", initial="0", description="护盾值"
        ),
        field("klass", "职阶", "text", choices=CLASSES, description="英灵的职阶"),
        field("str", "筋力", "number", choices=RANKS, description="决定近战攻击和近战物理伤害"),
        field("agi", "敏捷", "number", choices=RANKS, description="决定速度、远程物理伤害、闪避"),
        field("con", "耐久", "number", choices=RANKS, description="决定生命值"),
        field("int", "魔力", "number", choices=RANKS, description="决定魔力值、魔力豁免"),
        field(
            "luk",
            "幸运",
            "number",
            choices=RANKS,
            description="天意；幸运豁免、失去御主后还能存在多久",
        ),
        field("np", "宝具", "number", choices=RANKS, description="宝具的等级"),
        field("spirit_form", "灵体化中", "number", "runtime", min="0", max="1", initial="0"),
        field("riding", "骑乘中", "number", "runtime", min="0", max="1", initial="0"),
        field("masterless", "失去御主", "number", "runtime", min="0", max="1", initial="0"),
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
            'lookup(independent_days, max(con, int)) * 1440 if klass == "Archer" else 0',
            "min",
        ),
    ],
    "damage_taken": 'max(0, amount - 5 * servant.anti_magic.level) if kind == "magic" else amount',
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
                    "进入或解除灵体化：普通人看不见，物理上碰不到也不能攻击，速度提升 30%；被感知的距离不变。不消耗魔力。",
                    """
                    target = "self"
                    """,
                    """
                    self.set(spirit_form, 0 if spirit_form else 1)
                    if not spirit_form:
                        self.set(riding, 0)
                    """,
                    effects=[
                        {
                            "description": "灵体化时速度提升 30%",
                            "target": "move_speed",
                            "formula": "move_speed * 1.3 if spirit_form else move_speed",
                            "priority": None,
                        }
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
            ],
            hidden=True,
        ),
        group(
            "klass_skill",
            "职阶技能",
            [
                preset(
                    "骑乘",
                    "ride",
                    "骑上或跳下坐骑：骑乘时速度 + 骑乘等级 × 5 米/秒。灵体化时不能骑乘。骑上时按技能等级消耗魔力。",
                    """
                    target = "self"
                    requires = not spirit_form
                    """,
                    """
                    if not riding:
                        self.sub(mp, lookup(skill_cost, this.level))
                    self.set(riding, 0 if riding else 1)
                    """,
                    effects=[
                        {
                            "description": "骑乘时速度 + 骑乘等级 × 5 米/秒",
                            "target": "move_speed",
                            "formula": "move_speed + this.level * 300 if riding else move_speed",
                            "priority": None,
                        }
                    ],
                    when=is_class("Rider", "Saber"),
                ),
                preset(
                    "对魔力",
                    "anti_magic",
                    "受到魔力伤害（魔术、魔术攻击）时，无视其中 5/10/15/20/25 点（E~A），EX 为 50 点。宝具伤害一般不算魔力伤害。",
                    when=is_class("Saber", "Archer", "Lancer", "Rider"),
                ),
                preset(
                    "气息遮蔽",
                    "presence_concealment",
                    "隐藏自己的气息：别人发现你要掷出 10 + 等级 × ⌈距离÷40 米⌉（EX 按 6 算）；200 米外发现不了。"
                    "御主用 1d20+感知，英灵用 1d20+魔力+敏捷。攻击会暴露给对象；对方没发现你时，近战伤害骰变成 d12，对方也躲不开。",
                    when=is_class("Assassin"),
                ),
                preset(
                    "阵地作成",
                    "territory",
                    "花一天布置自己的阵地（半径约 125 米）。有人闯入时你会知道；在阵地中每分钟额外恢复等级点魔力（由 KP 按位置执行）。",
                    """
                    target = "none"
                    range = 1
                    cast_time = 1440
                    placement = placement(radius=125, perceive=0.2, notify=True)
                    """,
                    """
                    pass
                    """,
                    when=is_class("Caster"),
                ),
                preset(
                    "狂化",
                    "madness",
                    "狂战士的狂化。效果和等级由御主决定，请直接和 KP 商量。",
                    when=is_class("Berserker"),
                ),
            ],
            fields=[
                field("level", "等级", "number", choices=RANKS),
            ],
            placements=True,
        ),
        group(
            "personal_skill",
            "保有技能",
            [],
            fields=[
                field("level", "等级", "number", choices=RANKS),
            ],
            max_count=None,
            placements=True,
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
                    hit = target.is_muggle or level >= 1    # 对普通人必定生效
                    """,
                    "pass",
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
                    "pass",
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
            [
                preset(
                    "真名解放",
                    "true_name",
                    "解放宝具真名的攻击：伤害按宝具等级（A 5d12+9、B 5d10+7、C 4d10+5、D 3d10+3、E 3d6+1、EX 6d12+15）。"
                    "对方只能闪避，不能反击。100 米内：对城、对界默认困难成功，对人、对军默认极难成功；"
                    "更远：对城、对界极难成功，对人、对军困难成功。消耗：技能等级的魔力 × 类型倍数（对人 1、对军 3、对城 5、对界 10）。",
                    """
                    target = "single"
                    range = None
                    visible = True
                    noise = 1000
                    requires = not spirit_form and mp >= lookup(skill_cost, np) * lookup(np_cost, this.np_type)
                    auto_level = (3 if near else 2) if small else (2 if near else 3)
                    reactions = ["dodge"]
                    """,
                    """
                    near = distance <= 100
                    small = this.np_type == "对人" or this.np_type == "对军"
                    self.sub(mp, lookup(skill_cost, np) * lookup(np_cost, this.np_type))
                    target.damage(dice(lookup(np_dice_count, np), lookup(np_dice_sides, np)) + lookup(np_bonus, np))
                    """,
                ),
            ],
            fields=[
                field("np_type", "宝具类型", "text", choices=["对人", "对军", "对城", "对界"]),
            ],
            damage_kind="noble_phantasm",
            max_count=3,
            placements=True,
        ),
        defense_group(SERVANT_MELEE_DMG),
    ],
}

TABLES = [
    table("class_hp", by_class([16, 14, 14, 14, 10, 12, 18])),
    table("class_melee", by_class([10, 8, 10, 10, 4, 6, 12])),
    table("class_speed", by_class([6, 8, 7, 9, 5, 8, 6])),
    table("class_heal", by_class([1, 1, 1.1, 1, 1.2, 0.9, 1.3])),
    # 技能施放的魔力：E~A 1~5，EX 8
    table("skill_cost", by_rank([1, 2, 3, 4, 5, 8])),
    table("np_cost", [("对人", 1), ("对军", 3), ("对城", 5), ("对界", 10)]),
    table("np_dice_count", by_rank([3, 3, 4, 5, 5, 6])),
    table("np_dice_sides", by_rank([6, 10, 10, 10, 12, 12])),
    table("np_bonus", by_rank([1, 3, 5, 7, 9, 15])),
    # 豁免的修正：E~A -4/-2/0/+2/+4，EX +8
    table("save_mod", by_rank([-4, -2, 0, 2, 4, 8])),
    # 单独行动：没有御主也能存在的天数
    table("independent_days", by_rank([1, 3, 6, 10, 15, 30])),
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
    引擎已经执行的规则（检定、对抗、伤害、魔力、隐匿、死亡）不用 KP 再算。下面这些由 KP 按叙事处理：

    1. 通讯：英灵和御主任何一方进入战斗，除非另一方对战场有额外的观测手段，否则视作双方共感、同时进入战斗状态，无视距离。战斗中不准和队友交流。
       没有共感也没有观测手段时，英灵想和御主通讯：这一回合的行动视为困难，并且无法在紧急时刻回避攻击。
    2. 狂化：等级和效果由御主决定，和 KP 商量后写进角色卡。
    3. 宝具和保有技能：玩家可以自己设计，须经过 KP 审核。宝具特效需要对抗魔力或幸运时，技能设置写 save = "magic_save" 或 "luck_save"，difficulty 写宝具等级。其他特效依照 Fate 原作的宝具效果比对。
    4. “+”：每个英灵最多 3 个，分配在属性、技能或宝具上；每天一次、最多 10 分钟提升效果（+50%/+100%/+150%），爆发性宝具每个 + 效果多 0.5 倍；由幸运决定是否发动成功。初版由 KP 裁定。
    5. 宝具的范围效果：对军以上的宝具波及范围内的其他人，由 KP 声明范围查询后裁定。
    6. 暗示、使魔、瞬间移动、强化、傀儡兵等魔术的叙事效果由 KP 裁定；能消耗的魔力照常扣。
    7. 阵地作成：Caster 在自己的阵地里每分钟额外恢复等级点魔力，由 KP 在阵地内时用补魔类的叙述处理。
    """
)

PACK = {
    "world": {
        "name": "圣杯战争",
        "description": "以 Fate 系列的圣杯战争为基础，设定以原作为准。\n基调：严肃、紧张的异能战斗，伴随阴谋与背叛。死亡是真实的，没有复活。",
        "canon": "Type-Moon 圣杯战争",
        "reference_sites": ["https://www.tmdict.com/zh/"],
    },
    "templates": [MASTER, SERVANT],
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
                    "can_fly": False,
                    "str": 0,
                    "agi": 1,
                    "con": 1,
                    "int": 4,
                    "per": 2,
                    "cha": 2,
                    "weapon_db": 0,
                    "is_muggle": False,
                },
            },
            "expected": {"hp_max": 34, "mp_max": 22, "ap": 4, "perception_radius": 70},
        },
        {
            "name": "示例英灵",
            "template": "servant",
            "sheet": {
                "name": "示例英灵",
                "fields": {
                    "appearance": "身穿蓝银铠甲、手持看不见的剑的骑士",
                    "can_fly": False,
                    "klass": "Saber",
                    "str": 5,
                    "agi": 3,
                    "con": 4,
                    "int": 2,
                    "luk": 4,
                    "np": 5,
                },
                "preset_fields": {
                    "klass_skill": {"骑乘": {"level": 2}, "对魔力": {"level": 5}},
                    "noble_phantasm": {"真名解放": {"np_type": "对城"}},
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
