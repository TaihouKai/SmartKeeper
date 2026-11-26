"""各模块的接口定义。实现只在 web/app.py 装配，经构造函数注入。"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Literal, Protocol

from pydantic import JsonValue

from smartkeeper.contracts.adjudication import AdHocCheck, CheckResult, DiceResult, PatchOp
from smartkeeper.contracts.errors import Problem
from smartkeeper.contracts.events import Audience, Event, EventType, NewEvent
from smartkeeper.contracts.game import RoundStatus
from smartkeeper.contracts.geometry import Point
from smartkeeper.contracts.rulepack import (
    CheckSpec,
    RulePack,
    RulePackDraft,
    RulePackInfo,
    RulePackVersion,
)
from smartkeeper.contracts.sheet import BudgetUse, DerivedValue, Effect, ScriptStep, SkillConfig
from smartkeeper.contracts.spatial import (
    Body,
    DocEntry,
    Handle,
    IntelValue,
    LosResult,
    MapChange,
    MapData,
    QueryResult,
    SweepShape,
)

type State = dict[str, JsonValue]


class EventLog(Protocol):
    """只追加的事件日志。view_for 的唯一实现。"""

    def append(self, game_id: str, round_no: int, events: Sequence[NewEvent]) -> list[Event]:
        """在一个事务里追加一批事件，seq 在局内严格递增。"""
        ...

    def view_for(
        self,
        game_id: str,
        audience: Audience,
        since_seq: int = 0,
        types: Sequence[EventType] | None = None,
        round_no: int | None = None,
    ) -> list[Event]:
        """按受众过滤的事件。audience 为玩家 id、"kp" 或 "public"。匿名广播在非 KP 视图里隐去 actor。"""
        ...

    def get(self, game_id: str, seq: int) -> Event | None: ...


class RulePackStore(Protocol):
    """规则包的存储与版本。版本不可变。"""

    def create_pack(self, name: str) -> str: ...

    def save_version(self, pack_id: str, pack: RulePack) -> RulePackVersion:
        """校验通过才保存，否则抛 ValidationFailed。保存成功后这个规则包的草稿被删除。"""
        ...

    def save_draft(self, pack_id: str, pack: RulePack) -> RulePackDraft:
        """保存（覆盖）草稿，不做内容校验。"""
        ...

    def get_draft(self, pack_id: str) -> RulePackDraft: ...

    def delete_draft(self, pack_id: str) -> None:
        """删除草稿；规则包没有任何版本时连规则包一起删除。"""
        ...

    def get_version(self, pack_id: str, version: int) -> RulePackVersion: ...

    def list_packs(self) -> list[RulePackInfo]: ...

    def delete_version(self, pack_id: str, version: int) -> None:
        """调用方负责先确认该版本没有被任何一局使用。"""
        ...


class Rules(Protocol):
    """规则包的校验、公式求值、检定结算。纯函数，不依赖 LLM，不产生随机数。"""

    def validate_pack(self, pack: RulePack) -> list[Problem]: ...

    def validate_formula(
        self,
        pack: RulePack,
        template: str | None,
        formula: str,
        in_entry: str | None = None,
        scope: FormulaScope | None = None,
        other: str = "",
        names: Sequence[str] = (),
    ) -> list[Problem]:
        """校验一条公式：语法、函数白名单、引用的名字是否存在。in_entry 为分组名时允许 this.<列>
        （和这个分组的默认参数，再加上 names：条目、用途自己加的参数）。

        scope 不给时：有 template 按模板校验，没有按检定结果条件校验（可用 roll、target 等）。
        any_entity：任何模板的名字都可以（检定目标值、命名公式）；dice：同上并允许掷骰；
        dice 且给了 template：掷骰公式字段，按这个模板（和条目）校验并允许掷骰；
        script：技能脚本（按这个模板和条目校验）。
        """
        ...

    def complete_names(
        self, pack: RulePack, template: str | None, scope: FormulaScope | None = None
    ) -> list[str]:
        """公式输入框可补全的名字（scope=script 时加上脚本的语句开头）。"""
        ...

    def bonus_effects(self, bonus: str) -> tuple[Effect, ...]:
        """常驻加成的代码编译成一串修正（写错的是空）。"""
        ...

    def docs(self) -> tuple[DocEntry, ...]:
        """语法手册的目录：公式、技能设置、脚本、检定代码的全部写法（说明是翻译键）。"""
        ...

    def validate_sheet(
        self, pack: RulePack, template: str, sheet: JsonValue, peers: Peers | None = None
    ) -> list[Problem]:
        """按模板校验角色卡：字段存在、类型与单位、资源不越界、推导值不可直接写。"""
        ...

    def init_sheet(
        self, pack: RulePack, template: str, sheet: JsonValue, peers: Peers | None = None
    ) -> JsonValue:
        """建角提交后补上运行值的初值。"""
        ...

    def full_sheet(
        self, pack: RulePack, template: str, sheet: JsonValue, peers: Peers | None = None
    ) -> JsonValue:
        """角色卡加上此刻生效的固定条目（规则包分组里带条件的条目）。给人和 KP 看、查能力时用它；
        世界状态里存的卡不含固定条目。卡的结构不合法时原样返回。"""
        ...

    def derive(
        self, pack: RulePack, template: str, sheet: JsonValue, peers: Peers | None = None
    ) -> list[DerivedValue]: ...

    def derived_value(
        self,
        pack: RulePack,
        template: str,
        sheet: JsonValue,
        name: str,
        peers: Peers | None = None,
    ) -> float: ...

    def budgets(self, pack: RulePack, template: str, sheet: JsonValue) -> list[BudgetUse]:
        """这张卡在模板的每一项合计上限（例如属性点）上用了多少、最多多少。卡的结构不合法时是空表。"""
        ...

    def describe(
        self,
        pack: RulePack,
        template: str,
        sheet: JsonValue,
        names: tuple[str, ...],
        peers: Peers | None = None,
    ) -> tuple[IntelValue, ...]:
        """角色卡上这些字段或推导值此刻的值（经过修正），给情报用。卡上没有、算不出来的跳过。"""
        ...

    def describe_entries(
        self,
        pack: RulePack,
        template: str,
        sheet: JsonValue,
        group: str,
        peers: Peers | None = None,
    ) -> tuple[tuple[str, tuple[IntelValue, ...]], ...]:
        """一个分组里的全部条目（含生效的固定条目）：条目名和建角时填的列（不含使用时填写的、隐藏的）。"""
        ...

    def check_dice(self, pack: RulePack, check: str) -> str:
        """命名检定用的骰子公式。"""
        ...

    def roll(
        self,
        pack: RulePack,
        expr: str,
        faces: Faces,
        template: str | None = None,
        sheet: JsonValue = None,
        entry: dict[str, JsonValue] | None = None,
        peers: Peers | None = None,
        target: tuple[str, JsonValue, Peers | None] | None = None,
        extra: Mapping[str, float] | None = None,
    ) -> DiceResult:
        """求值一条可以掷骰的公式（例如 1d100、1d str、highest(4, 6, 3)）。

        给了 template 和 sheet 时公式可以引用这张卡上的名字；再给 entry（条目的字段）时可以用 this.<字段>。
        extra 是引擎另外给的名字（例如 distance、level），优先于卡上的名字。
        faces 由 engine 提供，是唯一的随机来源。
        """
        ...

    def plan_script(
        self,
        pack: RulePack,
        script: str,
        faces: Faces,
        template: str,
        sheet: JsonValue,
        entry: dict[str, JsonValue],
        peers: Peers | None = None,
        target: tuple[str, JsonValue, Peers | None] | None = None,
        config: str = "",
        outcome: Mapping[str, float] | None = None,
        damage_kind: str = "",
        scale: float = 1.0,
    ) -> tuple[ScriptStep, ...]:
        """技能脚本（scale 是这次的效果倍数，乘在伤害和增加的数值上；config 是同一条目的技能设置，脚本里可以用它的各项）：在使用者的角色卡和这个条目（entry 是它的列，含这次使用时填写的数）上，
        掷骰算好每一句的数值；modify 的公式除了被修正的推导值自己，其余名字都换成此刻的值。
        没有对象（target 为 None）时跳过作用在 target 上的句子。出错抛 ValidationFailed。"""
        ...

    def check_spec(self, pack: RulePack, name: str) -> CheckSpec:
        """规则包里一个检定的内容（解析它的代码）。没有这个检定抛 NotFound，代码写错抛 ValidationFailed。"""
        ...

    def choice_allowed(self, choices: tuple[str, ...], value: float) -> bool:
        """数值的可选值（E=1、1~5……）里有没有这个数。可选值写错时 False。"""
        ...

    def first_choice(self, choices: tuple[str, ...]) -> float | None:
        """可选值里的第一个数（参数没给时用它）；没有或写错时 None。"""
        ...

    def skill_config(self, config: str, script: str = "") -> SkillConfig:
        """条目的技能设置文本解析成 SkillConfig（没写的项取默认；script 是同一条目的技能脚本，
        设置里可以用它最外层的变量）。写错抛 ValidationFailed。"""
        ...

    def resolve_check(
        self,
        pack: RulePack,
        *,
        entity: str,
        template: str,
        sheet: JsonValue,
        check: str,
        roll: DiceResult,
        difficulty: float | None = None,
        opponent: tuple[str, str, JsonValue, DiceResult] | None = None,
        peers: Peers | None = None,
        opp_check: str | None = None,
        distance: float = 0.0,
        vs_template: str = "",
    ) -> CheckResult:
        """按检定代码算出等级（数字，1 起是成功）。opponent = (实体 id, 模板, 角色卡, 对手的骰子)；
        opp_check 是对手做的检定（默认是这个检定的 opposed_by，再默认同名检定），对手的等级另算（opp_level），
        难度只算在发起的一方。distance 是到对象的距离；vs_template 是没有对抗时对象的模板。"""
        ...

    def stealth(
        self,
        pack: RulePack,
        hider: tuple[str, JsonValue, Peers | None],
        observer: tuple[str, JsonValue, Peers | None],
        distance: float,
    ) -> float:
        """观察者在 distance 米外发现隐匿者的难度（隐匿者模板的 stealth 公式）；0 及以下是不隐匿。
        hider、observer 是 (模板, 角色卡, 同伴)。写错抛 ValidationFailed。"""
        ...

    def resolve_adhoc(self, entity: str, spec: AdHocCheck, roll: DiceResult) -> CheckResult:
        """临时检定：骰子公式加目标值，结果只有成功（1）/ 失败（0）。"""
        ...

    def render(self, pack: RulePack) -> str:
        """规则书：规则包渲染出的全文。"""
        ...


class World(Protocol):
    """世界状态的折叠与 patch 校验。"""

    def initial_state(self, map_id: str | None) -> State: ...

    def apply(self, state: State, ops: Sequence[PatchOp]) -> State:
        """应用 patch，返回新状态；失败抛 ValidationFailed，原状态不变。"""
        ...

    def validate(self, state: State, pack: RulePack) -> list[Problem]:
        """整份世界状态是否符合规则包里的模板。"""
        ...

    def expire(self, state: State, now_second: int) -> list[PatchOp]:
        """到期需要移除的状态。"""
        ...

    def canonical(self, state: State) -> str:
        """稳定的序列化，用于快照比较。"""
        ...


class RoundMachine(Protocol):
    def transition(self, status: RoundStatus, action: str) -> RoundStatus:
        """非法转换抛 IllegalState。"""
        ...


class RandomSource(Protocol):
    def randint(self, a: int, b: int) -> int: ...


type Faces = Callable[[int, int], tuple[int, ...]]
"""(个数, 面数) -> 每颗骰子的点数。"""

# 同一个玩家控制的其他实体：模板名 -> 角色卡；同一个模板有不止一个时为 None（引用它会报错）
type Peers = Mapping[str, JsonValue | None]
type FormulaScope = Literal[
    "any_entity", "dice", "script", "config", "check", "damage", "stealth", "search", "bonus"
]


class Dice(Protocol):
    def faces(self, count: int, sides: int) -> tuple[int, ...]:
        """掷 count 颗 sides 面骰。随机数只在这里产生；调用方（engine）负责写 dice_roll 事件。"""
        ...


class MapStore(Protocol):
    """地图文件的读取与校验。运行时只读文件，不联网。"""

    def load(self, map_id: str) -> MapData: ...

    def list_ids(self) -> list[str]: ...

    def save(self, map_id: str, text: str) -> MapData:
        """校验后保存一份地图文件（GeoJSON 文本）。"""
        ...


class Spatial(Protocol):
    """空间查询。纯函数：输入地图、地图变化和位置，输出命中清单。"""

    def within(
        self,
        m: MapData,
        changes: Sequence[MapChange],
        bodies: Sequence[Body],
        center: Point,
        radius: float,
    ) -> QueryResult: ...

    def sweep(
        self, m: MapData, changes: Sequence[MapChange], bodies: Sequence[Body], shape: SweepShape
    ) -> QueryResult: ...

    def line_of_sight(
        self, m: MapData, changes: Sequence[MapChange], a: Point, b: Point
    ) -> LosResult: ...

    def perceivable(
        self, m: MapData, changes: Sequence[MapChange], observer: Body, bodies: Sequence[Body]
    ) -> list[str]:
        """观察者能感知到的实体（不含自己）。"""
        ...

    def distance(self, a: Point, b: Point) -> float: ...

    def locate(
        self, m: MapData, name: str | None = None, point: Point | None = None
    ) -> list[str]: ...

    def in_bounds(self, m: MapData, p: Point) -> bool: ...

    def inside_feature(self, m: MapData, feature_id: str, p: Point) -> bool: ...

    def feature_within(
        self,
        m: MapData,
        changes: Sequence[MapChange],
        feature_id: str,
        center: Point,
        radius: float,
    ) -> bool:
        """某个地物是否在球内（用于判断玩家是否看见了地图变化）。"""
        ...


class HandleStore(Protocol):
    """代号：按玩家存放，每个玩家一套。"""

    def get(self, player_id: str, entity_id: str) -> Handle | None: ...

    def by_ref(self, player_id: str, ref: str) -> Handle | None: ...

    def list(self, player_id: str) -> list[Handle]: ...

    def ensure(self, player_id: str, entity_id: str) -> Handle:
        """没有代号时分配一个临时代号（#n），等“外观代号”调用命名。"""
        ...

    def set_label(
        self, player_id: str, entity_id: str, label: str, *, by_player: bool
    ) -> Handle: ...

    def set_note(self, player_id: str, entity_id: str, note: str) -> Handle: ...
