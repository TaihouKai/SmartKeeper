"""裁定 JSON 及相关结果类型。"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field, JsonValue

from smartkeeper.contracts.base import Frozen
from smartkeeper.contracts.geometry import Location, PlaceNameIn, Point


class PatchOp(Frozen):
    """RFC 6902 JSON Patch 的一个操作。"""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    op: Literal["add", "remove", "replace", "move", "copy", "test"]
    path: str
    value: JsonValue = None
    from_: str | None = Field(default=None, alias="from")


class Outcome(Frozen):
    player_id: str
    resolves: tuple[str, ...] = ()
    result: str
    observations: tuple[str, ...] = ()
    # 他必须停下来应对（被搭话、被拦住去路、出了他不能不管的事）：行动到此结束。
    # 不写时只是通知（察觉到有人进出、听到动静），行动照常继续，玩家可以自己改主意。
    # 被攻击、被移动、角色卡被改、踩到设置物时引擎自己让他停下，不看这一项。
    interrupt: bool = False


class Encounter(Frozen):
    players: tuple[str, ...]
    observed_by: dict[str, str]


class Movement(Frozen):
    entity: str
    to: Point
    inside: str | None = None
    because: str  # 行动条目 id，或 npc:<实体 ID>
    ability: str | None = None  # 依据某个能力的特殊移动


class PlaceIn(Frozen):
    """裁定里放下一个设置物：参数取自设置者角色卡上那个条目的设置物参数。"""

    owner: str  # 设置者实体
    entry: str  # 条目名（技能名）
    at: Point
    inside: str | None = None
    because: str  # 行动条目 id，或 npc:<实体 id>
    params: dict[str, float] = {}  # 条目“使用时填写”的列这次填的数，例如 {"mp_spent": 5}


class UseResult(Frozen):
    """裁定里列出本轮实际发生了的“使用”（规划时引擎已经算好的 entry_used 事件）。没列出的当作没发生。

    打没打中由引擎按技能设置判（检定、对象的应对），hit 只为兼容旧数据保留，不起作用。
    """

    seq: int
    hit: bool = True


class ReactionChoice(Frozen):
    """被攻击的玩家对一次攻击的应对：不抵抗、用一个检定对抗、或者用一个能当反应的瞬发技能。"""

    seq: int  # 那次攻击（entry_used 事件）的 seq
    kind: Literal["none", "check", "skill"] = "none"
    check: str = ""  # kind=check：攻击技能设置里 reactions 列出的检定
    entry: str = ""  # kind=skill：自己的技能（名字或 ID）
    params: dict[str, float] = {}  # 技能“使用时填写”的列


class ReactionParam(Frozen):
    name: str
    label: str = ""
    min: float | None = None
    max: float | None = None


class ReactionSkill(Frozen):
    entry: str
    description: str = ""
    params: tuple[ReactionParam, ...] = ()


class ReactionPrompt(Frozen):
    """给被攻击的玩家：一次等他应对的攻击，和他能选的应对。"""

    seq: int
    entry: str  # 攻击技能的名字
    defender: str  # 被攻击的是他的哪个实体
    who: str | None = None  # 攻击者的外貌；感知不到攻击者时是 None
    checks: tuple[str, ...] = ()  # 能用来对抗的检定
    labels: dict[str, str] = {}  # 检定名 -> 显示名
    skills: tuple[ReactionSkill, ...] = ()  # 能当反应的技能


class AreaEffect(Frozen):
    query_id: str
    affected: tuple[str, ...]


class MemoryEntryIn(Frozen):
    entities: tuple[str, ...] = ()
    features: tuple[str, ...] = ()
    text: str


class IntelIn(Frozen):
    """裁定里给一个玩家的情报：他从本轮看到、听到、查到的东西里推断出了某个实体的什么。

    text 是线索（提到实体时写 {{实体 id}}）；fields 是对方卡上的字段名，值由引擎从卡上取（例如认出了真实身份）。
    """

    player: str
    about: str  # 实体 id
    text: str = ""
    fields: tuple[str, ...] = ()


class PublicIntelIn(Frozen):
    """所有玩家都知道的关于某个实体的事：广播里、公开场合说出的名字和身份（例如开场通知里的接待人）。

    引擎告诉每个玩家（控制这个实体的玩家除外），不要求见过。text、fields 同 IntelIn。
    """

    about: str  # 实体 id
    text: str = ""
    fields: tuple[str, ...] = ()


class TellIn(Frozen):
    """裁定里的转告：source 这一方（玩家 id，或者 NPC 的实体 id）把 about 在哪告诉了 player（玩家 id）。

    引擎把 source 关于 about 最近一次的目击复制给 player（时间还是当初目击的时间），source 没有就没有效果。
    两边此刻能不能说上话（在一起、打电话、念话……）由 KP 判，判了能才写。
    """

    source: str
    player: str
    about: str


class Adjudication(Frozen):
    """一回合的裁定。推进多久由引擎决定（最早结束的行动），KP 只裁定这段时间里发生的事。"""

    outcomes: tuple[Outcome, ...]
    encounters: tuple[Encounter, ...] = ()
    movements: tuple[Movement, ...] = ()
    area_effects: tuple[AreaEffect, ...] = ()
    uses: tuple[UseResult, ...] = ()  # 规划时算好的技能使用：生效了没有
    placements: tuple[PlaceIn, ...] = ()  # 新放下的设置物
    remove_placements: tuple[str, ...] = ()  # 被拆除、失效的设置物 id
    public_events: tuple[str, ...] = ()
    state_patch: tuple[PatchOp, ...] = ()
    memory_entries: tuple[MemoryEntryIn, ...] = ()
    intel: tuple[IntelIn, ...] = ()  # 玩家得知的关于别人的情报
    public_intel: tuple[PublicIntelIn, ...] = ()  # 所有玩家都知道了的（广播里说出的名字、身份）
    tells: tuple[TellIn, ...] = ()  # 谁把谁在哪告诉了谁（技能的 seen_within 按它判）
    places: tuple[PlaceNameIn, ...] = ()  # 新起名字的地点（所有玩家共用、永久有效）
    kp_notes: str | None = None
    game_over: bool = False


class DiceResult(Frozen):
    expr: str
    rolls: tuple[int, ...]  # 每颗骰子的点数（含 highest/lowest 舍弃的）
    total: float
    seq: int | None = None  # 对应的 dice_roll 事件


class CheckResult(Frozen):
    entity: str
    check: str
    roll: DiceResult
    target: float
    difficulty: float | None = None
    opponent: str | None = None
    opp_roll: DiceResult | None = None
    opp_target: float | None = None
    level: int  # 0 及以下失败，1 起成功，越大越好
    level_name: str = ""  # 规则包给这个等级起的名字（检定的 levels）；没有是空
    opp_level: int | None = None  # 对抗时对方按自己的检定算出的等级
    reason: str = ""

    @property
    def success(self) -> bool:
        return self.level >= 1


class AdHocCheck(Frozen):
    """规则包没有覆盖时 KP 声明的临时检定。"""

    dice: str  # 骰子公式，可以引用执行检定的实体的字段
    target: float
    success_when: Literal["roll<=target", "roll>=target"] = "roll<=target"


class Opening(Frozen):
    broadcast: str
    messages: dict[str, str]  # 玩家 id -> 开场私信
    places: tuple[PlaceNameIn, ...] = ()  # 开场时新起名字的地点
    public_intel: tuple[PublicIntelIn, ...] = ()  # 开场时所有玩家都知道的（广播里说出的名字、身份）
    positions: dict[str, Location] = {}  # 实体 id -> 初始位置；剧本没有指定的
