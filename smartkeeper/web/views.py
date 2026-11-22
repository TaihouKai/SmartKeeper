"""给玩家看的数据形状。玩家永远看不到实体 ID：一律换成他自己的代号引用（ref）。坐标附带经纬度。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, JsonValue

from smartkeeper.contracts import (
    ActionItem,
    ClaimRef,
    Event,
    Intent,
    Location,
    MapData,
    NotFound,
    Point,
    TargetRef,
    ValidationFailed,
)
from smartkeeper.engine import Engine
from smartkeeper.mapdata import to_lonlat


class LonLatPoint(BaseModel):
    x: float
    y: float
    z: float
    lon: float
    lat: float


def lonlat(m: MapData, p: Point) -> LonLatPoint:
    lon, lat = to_lonlat(m.origin.lon, m.origin.lat, p.x, p.y)
    return LonLatPoint(x=p.x, y=p.y, z=p.z, lon=lon, lat=lat)


# ---------------- 事件 ----------------


class EventOut(BaseModel):
    seq: int
    round_no: int
    type: str
    actor: Literal["kp", "me", "player", "engine", "anonymous"] | None
    actor_name: str | None
    payload: dict[str, JsonValue]
    created_at: str


def _intent_to_refs(engine: Engine, player_id: str, raw: JsonValue) -> JsonValue:
    intent = Intent.model_validate(raw)
    return RefIntent.from_intent(engine, player_id, intent).model_dump(mode="json")


def event_for_player(engine: Engine, player_id: str, e: Event, names: dict[str, str]) -> EventOut:
    payload = dict(e.payload)
    if e.type == "action_declared" and "intent" in payload:
        payload["intent"] = _intent_to_refs(engine, player_id, payload["intent"])
    if e.type == "character_approved":
        payload.pop("entities", None)
    if e.type == "character_submitted":
        payload = {}
    actor: Literal["kp", "me", "player", "engine", "anonymous"] | None
    name: str | None = None
    if e.actor is None:
        actor = "anonymous" if e.type == "broadcast" else None
    elif e.actor == "kp":
        actor = "kp"
    elif e.actor in ("engine", "admin"):
        actor = "engine"
    elif e.actor == player_id:
        actor, name = "me", names.get(player_id)
    else:
        actor, name = "player", names.get(e.actor, "?")
    return EventOut(
        seq=e.seq,
        round_no=e.round_no,
        type=e.type,
        actor=actor,
        actor_name=name,
        payload=payload,
        created_at=e.created_at.isoformat(),
    )


# ---------------- 行动意图：实体 ID <-> 玩家的 ref ----------------


class RefTarget(BaseModel):
    kind: Literal["entity", "feature", "point"]
    ref: str | None = None
    id: str | None = None
    point: Point | None = None


class RefItem(BaseModel):
    actor: str
    verb: str
    targets: list[RefTarget] = []
    destination: Location | None = None
    detail: str = ""


class RefClaim(BaseModel):
    text: str
    refs: list[str] = []
    features: list[str] = []


class RefIntent(BaseModel):
    """玩家这一侧的意图：实体一律用 ref 表示。确认提交时原样发回。"""

    items: list[RefItem]
    claims: list[RefClaim] = []
    quotes: list[int] = []
    unresolved: list[str] = []

    @staticmethod
    def from_intent(engine: Engine, player_id: str, intent: Intent) -> RefIntent:
        def ref(eid: str) -> str:
            return engine.ref_for_entity(player_id, eid) or "?"

        items = [
            RefItem(
                actor=ref(it.actor),
                verb=it.verb,
                targets=[
                    RefTarget(kind="entity", ref=ref(t.id))
                    if t.kind == "entity" and t.id
                    else RefTarget(kind=t.kind, id=t.id, point=t.point)
                    for t in it.targets
                ],
                destination=it.destination,
                detail=it.detail,
            )
            for it in intent.items
        ]
        claims = [
            RefClaim(text=c.text, refs=[ref(e) for e in c.entities], features=list(c.features))
            for c in intent.claims
        ]
        return RefIntent(
            items=items,
            claims=claims,
            quotes=list(intent.quotes),
            unresolved=list(intent.unresolved),
        )

    def to_intent(self, engine: Engine, player_id: str) -> Intent:
        def eid(r: str) -> str:
            try:
                return engine.entity_for_ref(player_id, r)
            except NotFound as e:
                raise ValidationFailed("action.unknown_ref", ref=r) from e

        items = tuple(
            ActionItem(
                actor=eid(it.actor),
                verb=it.verb,
                targets=tuple(
                    TargetRef(kind="entity", id=eid(t.ref))
                    if t.kind == "entity" and t.ref
                    else TargetRef(kind=t.kind, id=t.id, point=t.point)
                    for t in it.targets
                ),
                destination=it.destination,
                detail=it.detail,
            )
            for it in self.items
        )
        claims = tuple(
            ClaimRef(
                text=c.text, entities=tuple(eid(r) for r in c.refs), features=tuple(c.features)
            )
            for c in self.claims
        )
        return Intent(
            items=items, claims=claims, quotes=tuple(self.quotes), unresolved=tuple(self.unresolved)
        )


class EchoTarget(BaseModel):
    kind: str
    label: str
    ref: str | None = None
    id: str | None = None
    point: LonLatPoint | None = None


class EchoItem(BaseModel):
    actor_label: str
    verb: str
    targets: list[EchoTarget]
    destination: LonLatPoint | None = None
    destination_label: str | None = None
    detail: str


class ActionEcho(BaseModel):
    """“你的行动被理解为：……”。按玩家自己的代号回显，地点在地图上标出。"""

    text: str
    items: list[EchoItem]
    unresolved: list[str]
    intent: RefIntent


def echo(engine: Engine, game_id: str, player_id: str, text: str, intent: Intent) -> ActionEcho:
    m = engine.map_data(game_id)
    labels = {h.entity_id: h.label for h in engine.handles(player_id)}

    def label(eid: str) -> str:
        return labels.get(eid, "?")

    items: list[EchoItem] = []
    for it in intent.items:
        targets: list[EchoTarget] = []
        for t in it.targets:
            if t.kind == "entity" and t.id:
                targets.append(
                    EchoTarget(
                        kind="entity", label=label(t.id), ref=engine.ref_for_entity(player_id, t.id)
                    )
                )
            elif t.kind == "feature" and t.id:
                f = m.feature(t.id)
                targets.append(
                    EchoTarget(kind="feature", id=t.id, label=(f.name or t.id) if f else t.id)
                )
            elif t.point is not None:
                targets.append(EchoTarget(kind="point", label="", point=lonlat(m, t.point)))
        dest = dest_label = None
        if it.destination is not None:
            dest = lonlat(m, it.destination.pos)
            if it.destination.inside:
                f = m.feature(it.destination.inside)
                dest_label = (f.name or f.id) if f else it.destination.inside
        items.append(
            EchoItem(
                actor_label=label(it.actor),
                verb=it.verb,
                targets=targets,
                destination=dest,
                destination_label=dest_label,
                detail=it.detail,
            )
        )
    return ActionEcho(
        text=text,
        items=items,
        unresolved=list(intent.unresolved),
        intent=RefIntent.from_intent(engine, player_id, intent),
    )


# ---------------- 场景 ----------------


class PresenceOut(BaseModel):
    ref: str
    label: str
    note: str
    pos: LonLatPoint
    inside: str | None


class OwnOut(BaseModel):
    ref: str
    name: str
    pos: LonLatPoint | None
    inside: str | None
    presence: list[PresenceOut]


class SeenOut(BaseModel):
    ref: str
    label: str
    note: str


class ChangeOut(BaseModel):
    feature: str
    status: str
    above_z: float | None


class SceneOut(BaseModel):
    entities: list[OwnOut]
    map_changes: list[ChangeOut]
    seen: list[SeenOut]


def scene(engine: Engine, game_id: str, player_id: str) -> SceneOut:
    s = engine.scene(game_id, player_id)
    m = engine.map_data(game_id)
    return SceneOut(
        entities=[
            OwnOut(
                ref=e.ref,
                name=e.name,
                pos=lonlat(m, e.pos) if e.pos else None,
                inside=e.inside,
                presence=[
                    PresenceOut(
                        ref=p.ref, label=p.label, note=p.note, pos=lonlat(m, p.pos), inside=p.inside
                    )
                    for p in e.presence
                ],
            )
            for e in s.entities
        ],
        map_changes=[
            ChangeOut(feature=c.feature, status=c.status, above_z=c.above_z) for c in s.map_changes
        ],
        seen=[SeenOut(ref=x.ref, label=x.label, note=x.note) for x in s.seen],
    )
