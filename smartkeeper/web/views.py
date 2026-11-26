"""给玩家看的数据形状。玩家永远看不到实体 ID：一律换成他自己的代号引用（ref）。坐标附带经纬度。"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, JsonValue

from smartkeeper.contracts import (
    Event,
    IntelFact,
    Intent,
    Location,
    MapData,
    Point,
    Talk,
)
from smartkeeper.engine import Engine
from smartkeeper.mapdata import to_lonlat


class LonLatPoint(BaseModel):
    x: float
    y: float
    z: float
    lon: float
    lat: float


_TAG = re.compile(r"</?\s*player_text[^>]*>", re.IGNORECASE)


def _untag(text: str) -> str:
    """模型有时把 prompt 里包玩家文字的标签照抄进细节：显示时去掉。"""
    return _TAG.sub("", text).strip()


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
    if e.type.startswith("talk_"):
        # 对话的内容走 /api/talks；这里不能露出对方是玩家还是 KP 扮演的 NPC
        return EventOut(
            seq=e.seq,
            round_no=0,
            type=e.type,
            actor=None,
            actor_name=None,
            payload={"talk": e.payload.get("talk")},
            created_at=e.created_at.isoformat(),
        )
    payload = dict(e.payload)
    if e.type == "action_declared" and "intent" in payload:
        payload["intent"] = _intent_to_refs(engine, player_id, payload["intent"])
    if e.type == "character_approved":
        payload.pop("entities", None)
    if e.type == "character_submitted":
        payload = {}
    if e.type == "intel_gained":
        # 实体 id 不给玩家：换成他的代号
        payload = engine.intel_event_view(e.game_id, player_id, payload)
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
        round_no=0,  # 玩家看不到回合数：不能从回合切得快慢推断别人在做什么
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
    act_seconds: int = 0
    move_seconds: int = 0


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
                detail=_untag(it.detail),
                act_seconds=it.act_seconds,
                move_seconds=it.move_seconds,
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
    move_seconds: int
    act_seconds: int
    entry: str | None = None  # 用的是哪个技能（没用技能是 None）


class ActionEcho(BaseModel):
    """“你的行动被理解为：……，预计耗时……”。按玩家自己的代号回显，地点在地图上标出。

    确认时只发回 parse_id：解析结果（包括 KP 估的耗时）留在服务器上，玩家改不了。
    """

    parse_id: str
    text: str
    items: list[EchoItem]
    unresolved: list[str]
    total_seconds: int  # 各实体按顺序做完自己的条目，取最长的那个


def echo(
    engine: Engine, game_id: str, player_id: str, text: str, intent: Intent, parse_id: str
) -> ActionEcho:
    m = engine.map_data(game_id)
    labels = {h.entity_id: h.label for h in engine.handles(player_id)}

    def label(eid: str) -> str:
        return labels.get(eid, "?")

    # 地物的叫法：我知道名字的地点（例如教会所在的楼）优先，其次是地图上的名字；都没有是空，界面上写成“地图上的点”
    named = {
        p.feature: p.name for p in engine.known_places(game_id, player_id).values() if p.feature
    }

    def place_label(fid: str) -> str:
        f = m.feature(fid)
        return named.get(fid) or (f.name if f else "")

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
                targets.append(EchoTarget(kind="feature", id=t.id, label=place_label(t.id)))
            elif t.point is not None:
                targets.append(EchoTarget(kind="point", label="", point=lonlat(m, t.point)))
        dest = dest_label = None
        if it.destination is not None:
            dest = lonlat(m, it.destination.pos)
            if it.destination.inside:
                dest_label = place_label(it.destination.inside) or None
        items.append(
            EchoItem(
                actor_label=label(it.actor),
                verb=it.verb,
                targets=targets,
                destination=dest,
                destination_label=dest_label,
                detail=_untag(it.detail),
                move_seconds=it.move_seconds,
                act_seconds=it.act_seconds,
                entry=it.entry,
            )
        )
    per_actor: dict[str, int] = {}
    for it in intent.items:
        per_actor[it.actor] = per_actor.get(it.actor, 0) + it.move_seconds + it.act_seconds
    return ActionEcho(
        parse_id=parse_id,
        text=text,
        items=items,
        unresolved=list(intent.unresolved),
        total_seconds=max(per_actor.values(), default=0),
    )


# ---------------- 对话 ----------------


class TalkLineOut(BaseModel):
    seq: int
    mine: bool
    text: str


class TalkOut(BaseModel):
    """玩家看到的一场对话。对方一律用代号，不说明对方是玩家还是 NPC。"""

    id: str
    status: Literal["invited", "active", "declined", "ended"]
    incoming: bool  # 是不是别人邀请我
    me_ref: str
    me_name: str
    other_ref: str
    other_label: str
    lines: list[TalkLineOut]


def talk_for_player(engine: Engine, game_id: str, player_id: str, t: Talk) -> TalkOut:
    incoming = t.b_player == player_id
    mine, other = (t.b_entity, t.a_entity) if incoming else (t.a_entity, t.b_entity)
    labels = {h.entity_id: h.label for h in engine.handles(player_id)}
    return TalkOut(
        id=t.id,
        status=t.status,
        incoming=incoming,
        me_ref=engine.ref_for_entity(player_id, mine) or "?",
        me_name=engine.entity_name(game_id, mine),
        other_ref=engine.ref_for_entity(player_id, other) or "?",
        other_label=labels.get(other, "?"),
        lines=[TalkLineOut(seq=m.seq, mine=m.speaker == mine, text=m.text) for m in t.messages],
    )


# ---------------- 场景 ----------------


class PresenceOut(BaseModel):
    ref: str
    label: str
    note: str
    pos: LonLatPoint
    inside: str | None


class PlacementOut(BaseModel):
    ref: str
    label: str  # 自己放的才有名字
    pos: LonLatPoint
    radius: float
    mine: bool


class OwnOut(BaseModel):
    ref: str
    name: str
    pos: LonLatPoint | None
    inside: str | None
    presence: list[PresenceOut]
    placements: list[PlacementOut] = []


class SeenOut(BaseModel):
    ref: str
    label: str
    note: str
    intel: list[IntelFact] = []  # 我知道的关于他的事


class ChangeOut(BaseModel):
    feature: str
    status: Literal["destroyed"]
    above_z: float | None


class PlaceOut(BaseModel):
    """这个玩家知道名字的地点（名字和位置的对应对谁都一样）。feature 是所在的地物（例如这栋楼），没有是 None。"""

    id: str
    name: str
    pos: LonLatPoint
    inside: str | None
    feature: str | None


class SceneOut(BaseModel):
    entities: list[OwnOut]
    map_changes: list[ChangeOut]
    seen: list[SeenOut]
    places: list[PlaceOut] = []


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
                placements=[
                    PlacementOut(
                        ref=x.ref, label=x.label, pos=lonlat(m, x.pos), radius=x.radius, mine=x.mine
                    )
                    for x in e.placements
                ],
            )
            for e in s.entities
        ],
        map_changes=[
            ChangeOut(feature=c.feature, status=c.status, above_z=c.above_z) for c in s.map_changes
        ],
        seen=[SeenOut(ref=x.ref, label=x.label, note=x.note, intel=list(x.intel)) for x in s.seen],
        places=[
            PlaceOut(id=pid, name=p.name, pos=lonlat(m, p.pos), inside=p.inside, feature=p.feature)
            for pid, p in sorted(engine.known_places(game_id, player_id).items())
        ],
    )
