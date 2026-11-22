"""坐标与位置。引擎内部只用米：x 向东，y 向北，z 是离地高度。"""

from __future__ import annotations

from smartkeeper.contracts.base import Frozen


class Point(Frozen):
    x: float
    y: float
    z: float = 0.0


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
