"""各模块的接口定义。实现只在 web/app.py 装配，经构造函数注入。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from pydantic import JsonValue

from smartkeeper.contracts.adjudication import AdHocCheck, CheckResult, DiceResult, PatchOp
from smartkeeper.contracts.errors import Problem
from smartkeeper.contracts.events import Audience, Event, EventType, NewEvent
from smartkeeper.contracts.game import RoundStatus
from smartkeeper.contracts.rulepack import RulePack, RulePackInfo, RulePackVersion
from smartkeeper.contracts.sheet import DerivedValue

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
        """校验通过才保存，否则抛 ValidationFailed。"""
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
        self, pack: RulePack, template: str | None, formula: str, in_entry: str | None = None
    ) -> list[Problem]:
        """校验一条公式：语法、函数白名单、引用的名字是否存在。in_entry 为分组名时允许 self.<字段>。"""
        ...

    def complete_names(self, pack: RulePack, template: str | None) -> list[str]:
        """公式输入框可补全的名字。"""
        ...

    def validate_sheet(self, pack: RulePack, template: str, sheet: JsonValue) -> list[Problem]:
        """按模板校验角色卡：字段存在、类型与单位、资源不越界、推导值不可直接写。"""
        ...

    def init_sheet(self, pack: RulePack, template: str, sheet: JsonValue) -> JsonValue:
        """建角提交后补上运行值的初值。"""
        ...

    def derive(self, pack: RulePack, template: str, sheet: JsonValue) -> list[DerivedValue]: ...

    def derived_value(
        self, pack: RulePack, template: str, sheet: JsonValue, name: str
    ) -> float: ...

    def check_dice(self, pack: RulePack, check: str) -> str:
        """命名检定用的骰子表达式。"""
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
    ) -> CheckResult:
        """按成功条件算出结果等级。opponent = (实体 id, 模板, 角色卡, 对手的骰子)。"""
        ...

    def resolve_adhoc(self, entity: str, spec: AdHocCheck, roll: DiceResult) -> CheckResult:
        """临时检定：骰子表达式加目标值，结果只有 success / failure。"""
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

    def expire(self, state: State, now_minute: int) -> list[PatchOp]:
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


class Dice(Protocol):
    def validate(self, expr: str) -> list[Problem]: ...

    def roll(self, expr: str) -> DiceResult:
        """掷骰。随机数只在这里产生；调用方（engine）负责写 dice_roll 事件。"""
        ...
