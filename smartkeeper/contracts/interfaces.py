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
from smartkeeper.contracts.rulepack import RulePack, RulePackDraft, RulePackInfo, RulePackVersion
from smartkeeper.contracts.sheet import DerivedValue
from smartkeeper.contracts.spatial import (
    Body,
    Handle,
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
    ) -> list[Problem]:
        """校验一条公式：语法、函数白名单、引用的名字是否存在。in_entry 为分组名时允许 self.<字段>。

        scope 不给时：有 template 按模板校验，没有按检定结果条件校验（可用 roll、target 等）。
        any_entity：任何模板的名字都可以（检定目标值、命名公式）；dice：同上并允许掷骰；
        dice 且给了 template：掷骰公式字段，按这个模板（和条目）校验并允许掷骰。
        """
        ...

    def complete_names(self, pack: RulePack, template: str | None) -> list[str]:
        """公式输入框可补全的名字。"""
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
    ) -> DiceResult:
        """求值一条可以掷骰的公式（例如 1d100、1d str、highest(4, 6, 3)）。

        给了 template 和 sheet 时公式可以引用这张卡上的名字；再给 entry（条目的字段）时可以用 self.<字段>。
        faces 由 engine 提供，是唯一的随机来源。
        """
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
    ) -> CheckResult:
        """按成功条件算出结果等级。opponent = (实体 id, 模板, 角色卡, 对手的骰子)。"""
        ...

    def resolve_adhoc(self, entity: str, spec: AdHocCheck, roll: DiceResult) -> CheckResult:
        """临时检定：骰子公式加目标值，结果只有 success / failure。"""
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
type FormulaScope = Literal["any_entity", "dice"]


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
