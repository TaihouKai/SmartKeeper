"""坐标与位置。引擎内部只用米：x 向东，y 向北，z 是离地高度。"""

from __future__ import annotations

from pydantic import Field

from smartkeeper.contracts.base import Frozen


class Point(Frozen):
    x: float
    y: float
    z: float = 0.0


class Placement(Frozen):
    """地图上的设置物（陷阱、结界等），世界状态 /placements/<id>。只有引擎能写。"""

    owner: str  # 设置者实体
    entry: str  # 来自设置者角色卡上的哪个条目
    description: str = ""
    pos: Point
    inside: str | None = None
    radius: float
    perceive_multiplier: float = 1.0
    charges: int | None = None  # 剩余可触发次数；None 表示无限
    expires_at: int | None = None  # 游戏内秒；None 表示一直存在
    notify_owner: bool = True
    created_at: int = 0
    known_by: tuple[str, ...] = ()  # 触发过它的实体：从此知道它在那里，不管感知系数
    # 整栋建筑：设置物就是这栋建筑（地物 id），在建筑里就算在范围内，radius 不用
    building: str | None = None


class Location(Frozen):
    pos: Point
    inside: str | None = None  # 所在建筑的地物 id


class Place(Frozen):
    """写剧本和开场时用的位置：可以直接给坐标，也可以给地图上的地名（引擎解析成坐标）。

    - place：地物的名字或 id，例如 "新宿駅"；在建筑里时实体就在这栋楼内
    - floor：楼层（1 是地面层，负数是地下）；roof=true 表示楼顶
    - pos / inside：直接给坐标（米）
    """

    place: str | None = None
    floor: int | None = None
    roof: bool = False
    pos: Point | None = None
    inside: str | None = None


class NamedPlace(Frozen):
    """KP 或剧本给地图上一个位置起的名字，世界状态 /places/<id>。

    一个名字只指一个地方，起了就一直有效，所有玩家看到的都一样（地图上显示，消息里可以点）。
    feature 是这个位置所在的地物（例如这栋楼），没有是 None。
    """

    name: str
    pos: Point
    inside: str | None = None
    feature: str | None = None


class PlaceNameIn(Frozen):
    """给一个位置起名字：name 是名字，at 是位置（地图上的地名、已经起过的名字，或坐标）。"""

    name: str = Field(min_length=1, max_length=40)
    at: Place
