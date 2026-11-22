"""地图与空间查询的数据类型。坐标一律是以地图原点为基准的平面米制坐标。"""

from __future__ import annotations

from typing import Literal

from smartkeeper.contracts.actions import TargetRef
from smartkeeper.contracts.base import Frozen
from smartkeeper.contracts.geometry import Point

FeatureKind = Literal["building", "road", "park", "water", "landmark"]

# 平面几何：多边形是外环加若干内环；线是点列；点是一个坐标。全部单位米。
type Ring = tuple[tuple[float, float], ...]


class MapFeature(Frozen):
    id: str
    kind: FeatureKind
    name: str = ""
    polygon: tuple[Ring, ...] | None = None  # 外环在前，其余为洞
    line: Ring | None = None
    point: tuple[float, float] | None = None
    height: float = 0.0  # 顶高，米；只对建筑有意义
    min_height: float = 0.0  # 底高，米


class MapOrigin(Frozen):
    lon: float
    lat: float


class MapData(Frozen):
    id: str
    name: str
    origin: MapOrigin
    bounds: tuple[float, float, float, float]  # minx, miny, maxx, maxy（米）
    features: tuple[MapFeature, ...]
    attribution: str = "© OpenStreetMap contributors"

    def feature(self, fid: str) -> MapFeature | None:
        return next((f for f in self.features if f.id == fid), None)


class MapChange(Frozen):
    """世界状态 map_changes 里的一项。above_z 为空表示整栋被毁，否则只毁掉该高度以上的部分。"""

    feature: str
    status: Literal["destroyed"] = "destroyed"
    above_z: float | None = None
    known_by: tuple[str, ...] = ()
    public: bool = False


class Body(Frozen):
    """空间查询看到的实体：位置和感知相关的推导值。"""

    id: str
    pos: Point
    inside: str | None = None
    perception_radius: float = 0.0
    concealment: float = 1.0


class SweepShape(Frozen):
    """已经确定了尺寸和位置的扫掠形状。

    - capsule：线段 a→b 加半径 radius
    - box：从 origin 出发朝 toward 的水平方向，长 length、宽 width、高 height（以 origin.z 为中心）
    - sphere：球心 center、半径 radius
    - cone：顶点 origin，朝 toward，长 length，半角 angle（度）
    """

    kind: Literal["capsule", "box", "sphere", "cone"]
    a: Point | None = None
    b: Point | None = None
    origin: Point | None = None
    toward: Point | None = None
    center: Point | None = None
    radius: float | None = None
    length: float | None = None
    width: float | None = None
    height: float | None = None
    angle: float | None = None


class BuildingHit(Frozen):
    feature: str
    z_from: float
    z_to: float


class QueryResult(Frozen):
    entities: tuple[str, ...] = ()
    features: tuple[str, ...] = ()
    buildings: tuple[BuildingHit, ...] = ()


class LosResult(Frozen):
    visible: bool
    blockers: tuple[str, ...] = ()


class SpatialQuery(Frozen):
    """KP 在检定规划里声明的一次空间查询。

    - kind=within：center（或 center_entity）+ radius
    - kind=sweep：由 entity 的能力 ability 给出形状，KP 只给 toward；
      能力没有结构化参数时，KP 在 shape 里直接给尺寸（同样记入日志）
    - kind=line_of_sight：两个实体或点
    - kind=distance：两个实体或点
    - kind=locate：name 或 point
    """

    query_id: str
    kind: Literal["within", "sweep", "line_of_sight", "distance", "locate"]
    entity: str | None = None
    ability: str | None = None
    toward: TargetRef | None = None
    shape: SweepShape | None = None
    center: TargetRef | None = None
    radius: float | None = None
    a: TargetRef | None = None
    b: TargetRef | None = None
    name: str | None = None
    point: Point | None = None


class SpatialQueryResult(Frozen):
    query_id: str
    kind: str
    shape: SweepShape | None = None
    result: QueryResult | None = None
    los: LosResult | None = None
    distance: float | None = None
    features: tuple[str, ...] = ()


class PresenceEntry(Frozen):
    """在场列表的一项。PC 和 NPC 的字段完全相同，ref 是给这个玩家的不透明引用。"""

    ref: str
    label: str
    note: str = ""
    pos: Point
    inside: str | None = None


class SeenEntry(Frozen):
    ref: str
    label: str
    note: str = ""


class OwnEntity(Frozen):
    ref: str
    name: str
    pos: Point | None
    inside: str | None
    presence: tuple[PresenceEntry, ...]


class Scene(Frozen):
    entities: tuple[OwnEntity, ...]
    map_changes: tuple[MapChange, ...]
    seen: tuple[SeenEntry, ...]  # “见过的人”：感知过的全部实体，不在场时也能 @


class Handle(Frozen):
    player_id: str
    entity_id: str
    ref: str
    label: str
    note: str = ""
    auto: bool = True  # 代号由系统生成，尚未被玩家改名
    named: bool = False  # 已由“外观代号”调用命名
