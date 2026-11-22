"""一局、玩家、回合的数据类型。"""

from __future__ import annotations

from typing import Literal

from pydantic import JsonValue

from smartkeeper.contracts.base import Frozen

GameStatus = Literal["setup", "characters", "running", "ended"]
RoundStatus = Literal["collecting", "adjudicating", "review", "published"]


class GameSettings(Frozen):
    review_mode: bool = False
    web_search: bool = True
    kp_language: str = "zh"
    player_webhook: str | None = None
    admin_webhook: str | None = None


class GameConfig(Frozen):
    name: str
    rulepack_id: str
    rulepack_version: int
    map_id: str | None = None
    scenario_public: str = ""
    scenario_kp: str = ""
    settings: GameSettings = GameSettings()


class Game(Frozen):
    id: str
    name: str
    status: GameStatus
    rulepack_id: str
    rulepack_version: int
    map_id: str | None
    scenario_public: str
    scenario_kp: str
    settings: GameSettings
    current_round: int  # 0 表示尚未开场


class Player(Frozen):
    id: str
    game_id: str
    display_name: str
    ui_language: str = "zh"
    active: bool = True  # 邀请作废后为 False


class Round(Frozen):
    game_id: str
    no: int
    status: RoundStatus
    started_minute: int
    ended_minute: int | None = None
    forced: bool = False
    submitted: tuple[str, ...] = ()  # 结算时已提交行动的玩家
    draft: dict[str, JsonValue] | None = None  # 待审核的裁定与反馈草稿
    snapshot: dict[str, JsonValue] | None = None  # 发布后的世界状态快照


class Identity(Frozen):
    id: str
    name: str
    description: str = ""


class IdentityRules(Frozen):
    mode: Literal["draw", "choose"] = "draw"
    options: tuple[Identity, ...] = ()
