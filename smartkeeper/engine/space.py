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


CLOCK_KEY = "$clock"


def clock_of(state: State) -> dict[str, JsonValue]:
    """此刻的钟点：time 是一天里的几点（小时，带小数），day 是第几天（从 1 开始）。"""
    start = state.get("clock")
    secs = (start if isinstance(start, int) else 0) + int(cast(int, state.get("game_seconds", 0)))
    return {"time": round((secs % 86400) / 3600, 6), "day": secs // 86400 + 1}


def peers_of(state: State, entity_id: str) -> dict[str, JsonValue | None]:
    """同一个玩家控制的其他实体：模板名 -> 角色卡。同一个模板有不止一个时为 None（引用会报错）。
    另外带着此刻的钟点（键 $clock），公式里的 time / day 从这里取。"""
    ents = _obj(state.get("entities"))
    out: dict[str, JsonValue | None] = {CLOCK_KEY: clock_of(state)}
    for ctl in _obj(state.get("controls")).values():
        mine = [str(e) for e in ctl] if isinstance(ctl, list) else []
        if entity_id not in mine:
            continue
        for other in mine:
            if other == entity_id:
                continue
            ent = _obj(ents.get(other))
            tpl = str(ent.get("template", ""))
            out[tpl] = None if tpl in out else ent.get("sheet")
        return out
    return out


def partners_of(state: State, entity_id: str) -> dict[str, str]:
    """同一个玩家控制的其他实体：模板名 -> 实体 id（同一个模板有不止一个时不列）。"""
    ents = _obj(state.get("entities"))
    for ctl in _obj(state.get("controls")).values():
        mine = [str(e) for e in ctl] if isinstance(ctl, list) else []
        if entity_id not in mine:
            continue
        out: dict[str, str] = {}
        twice: set[str] = set()
        for other in mine:
            if other == entity_id:
                continue
            tpl = str(_obj(ents.get(other)).get("template", ""))
            if tpl in out:
                twice.add(tpl)
            out[tpl] = other
        return {k: v for k, v in out.items() if k not in twice}
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
        # 隐匿的角色：哪些观察者已经发现了它（引擎每轮开始时替观察者掷侦查）
        self.detected: dict[str, set[str]] = {}
        for eid, raw in self.entities.items():
            got = _obj(raw).get("detected_by")
            self.detected[eid] = {str(x) for x in got} if isinstance(got, list) else set()
        self._perceived: dict[str, list[str]] = {}
        self._sees: dict[str, list[str]] = {}
        self._hide: dict[tuple[str, str], float] = {}

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

    def sees(self, entity_id: str) -> list[str]:
        """只看距离和视线：在感知半径（乘对方的匿踪系数）内、看得见的实体。不管隐匿。"""
        hit = self._sees.get(entity_id)
        if hit is None:
            obs = self.bodies.get(entity_id)
            hit = (
                []
                if obs is None
                else self.spatial.perceivable(
                    self.map, self.changes, obs, list(self.bodies.values())
                )
            )
            self._sees[entity_id] = hit
        return hit

    def hiding(self, hider: str, observer: str) -> float:
        """观察者此刻发现隐匿者的难度（隐匿者模板的 stealth）；0 及以下是没在隐匿。公式出错当作不隐匿。"""
        key = (hider, observer)
        if key not in self._hide:
            h, o = _obj(self.entities.get(hider)), _obj(self.entities.get(observer))
            hb, ob = self.bodies.get(hider), self.bodies.get(observer)
            dist = self.spatial.distance(hb.pos, ob.pos) if hb and ob else 0.0
            try:
                self._hide[key] = self.rules.stealth(
                    self.pack,
                    (str(h.get("template", "")), h.get("sheet"), peers_of(self.state, hider)),
                    (str(o.get("template", "")), o.get("sheet"), peers_of(self.state, observer)),
                    dist,
                )
            except ValidationFailed:
                self._hide[key] = 0.0
        return self._hide[key]

    def perceived_by(self, entity_id: str) -> list[str]:
        """某个实体此刻能感知到的实体，即它的在场列表：看得见的，去掉还没发现的隐匿者。"""
        hit = self._perceived.get(entity_id)
        if hit is None:
            hit = [
                h
                for h in self.sees(entity_id)
                if entity_id in self.detected.get(h, set()) or self.hiding(h, entity_id) <= 0
            ]
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
