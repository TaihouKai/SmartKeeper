"""engine 里与位置、感知有关的计算。把世界状态翻译成 spatial 能用的 Body，再调用 spatial 接口。"""

from __future__ import annotations

from typing import cast

from pydantic import JsonValue

from smartkeeper.contracts import (
    Body,
    MapChange,
    MapData,
    MapOrigin,
    Point,
    RulePack,
    Rules,
    Spatial,
    State,
    ValidationFailed,
)

# 没有地图的局：无限大的空地图。感知只看距离，没有遮挡。
EMPTY_MAP = MapData(
    id="",
    name="",
    origin=MapOrigin(lon=0.0, lat=0.0),
    bounds=(-1e12, -1e12, 1e12, 1e12),
    features=(),
)


def _obj(v: JsonValue) -> dict[str, JsonValue]:
    return cast(dict[str, JsonValue], v) if isinstance(v, dict) else {}


def peers_of(state: State, entity_id: str) -> dict[str, JsonValue | None]:
    """同一个玩家控制的其他实体：模板名 -> 角色卡。同一个模板有不止一个时为 None（引用会报错）。"""
    ents = _obj(state.get("entities"))
    for ctl in _obj(state.get("controls")).values():
        mine = [str(e) for e in ctl] if isinstance(ctl, list) else []
        if entity_id not in mine:
            continue
        out: dict[str, JsonValue | None] = {}
        for other in mine:
            if other == entity_id:
                continue
            ent = _obj(ents.get(other))
            tpl = str(ent.get("template", ""))
            out[tpl] = None if tpl in out else ent.get("sheet")
        return out
    return {}


def point_of(raw: JsonValue) -> Point | None:
    p = _obj(raw)
    if not p:
        return None
    return Point.model_validate(p)


class Space:
    """某一时刻的世界状态在空间上的视图。"""

    def __init__(
        self, *, spatial: Spatial, m: MapData, state: State, pack: RulePack, rules: Rules
    ) -> None:
        self.spatial = spatial
        self.map = m
        self.state = state
        self.pack = pack
        self.rules = rules
        self.entities = _obj(state.get("entities"))
        self.controls: dict[str, list[str]] = {
            pid: [str(e) for e in v]
            for pid, v in _obj(state.get("controls")).items()
            if isinstance(v, list)
        }
        self.owner = {e: pid for pid, ents in self.controls.items() for e in ents}
        raw_changes = state.get("map_changes")
        self.changes = [
            MapChange.model_validate(c)
            for c in (raw_changes if isinstance(raw_changes, list) else [])
        ]
        self.bodies: dict[str, Body] = {}
        for eid, raw in self.entities.items():
            ent = _obj(raw)
            pos = point_of(ent.get("pos"))
            if pos is None:
                continue
            tpl = str(ent.get("template", ""))
            sheet = ent.get("sheet")
            peers = peers_of(state, eid)
            try:
                pr = self.rules.derived_value(pack, tpl, sheet, "perception_radius", peers)
                cc = self.rules.derived_value(pack, tpl, sheet, "concealment", peers)
            except ValidationFailed:
                pr, cc = 0.0, 1.0
            inside = ent.get("inside")
            self.bodies[eid] = Body(
                id=eid,
                pos=pos,
                inside=inside if isinstance(inside, str) else None,
                perception_radius=pr,
                concealment=cc,
            )
        self._perceived: dict[str, list[str]] = {}

    def full_sheet(self, entity_id: str) -> dict[str, JsonValue]:
        """实体的角色卡，含此刻生效的固定条目。"""
        ent = _obj(self.entities.get(entity_id))
        return _obj(
            self.rules.full_sheet(
                self.pack,
                str(ent.get("template", "")),
                ent.get("sheet"),
                peers_of(self.state, entity_id),
            )
        )

    def derived(self, entity_id: str, name: str) -> float:
        ent = _obj(self.entities.get(entity_id))
        return self.rules.derived_value(
            self.pack,
            str(ent.get("template", "")),
            ent.get("sheet"),
            name,
            peers_of(self.state, entity_id),
        )

    def perceived_by(self, entity_id: str) -> list[str]:
        """某个实体此刻能感知到的实体，即它的在场列表。"""
        hit = self._perceived.get(entity_id)
        if hit is None:
            obs = self.bodies.get(entity_id)
            hit = (
                []
                if obs is None
                else self.spatial.perceivable(
                    self.map, self.changes, obs, list(self.bodies.values())
                )
            )
            self._perceived[entity_id] = hit
        return hit

    def player_perceived(self, player_id: str) -> set[str]:
        """玩家的视图是他全部实体视图的并集；不含他自己的实体。"""
        mine = set(self.controls.get(player_id, []))
        out: set[str] = set()
        for e in mine:
            out |= set(self.perceived_by(e))
        return out - mine

    def player_sees_player(self, p: str, q: str) -> bool:
        """p 是否有实体能感知到 q 的某个实体。"""
        theirs = set(self.controls.get(q, []))
        return bool(self.player_perceived(p) & theirs)

    def feature_known(self, player_id: str, feature_id: str) -> bool:
        for e in self.controls.get(player_id, []):
            b = self.bodies.get(e)
            if b is not None and self.spatial.feature_within(
                self.map, self.changes, feature_id, b.pos, b.perception_radius
            ):
                return True
        return False
