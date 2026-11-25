"""一局、玩家、回合的数据类型。"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, JsonValue

from smartkeeper.contracts.base import Frozen

GameStatus = Literal["setup", "characters", "running", "ended"]
RoundStatus = Literal["collecting", "adjudicating", "review", "published"]


class LibraryCharacter(Frozen):
    """角色库里的一个角色（一整套卡，例如一个玩家要建的几张卡），属于一套规则书，和局分开存。
    设了密码的（locked），查看和使用都要密码。拿进一局时复制一份，局里的变化不写回角色库。"""

    id: str
    rulepack_id: str
    name: str
    summary: str = ""
    templates: tuple[str, ...] = ()  # 有哪些卡（模板名）
    locked: bool = False
    created_by: str = ""  # 创建者的昵称
    updated_at: str = ""


class LibraryCharacterFull(LibraryCharacter):
    sheets: JsonValue = None  # 和提交角色卡一样的格式：[{template, sheet}, ...]


class GameSettings(Frozen):
    review_mode: bool = False
    web_search: bool = True
    kp_language: str = "zh"
    player_webhook: str | None = None
    admin_webhook: str | None = None
    # 最短回合（秒）：回合结束时刻至少是开始时刻加这么多。功能已做好，默认 0 即不生效。
    min_round_seconds: int = Field(default=0, ge=0)
    # 在首页的房间列表里列出；建角阶段任何人填个名字就能直接加入（不用邀请链接）
    lobby: bool = True


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
    started_second: int  # 游戏内时刻（秒）
    ended_second: int | None = None  # 结算开始时由引擎定下的结束时刻
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
