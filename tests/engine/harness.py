"""engine 测试的装配：各模块的真实实现加内存 SQLite。"""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlalchemy as sa
from pydantic import JsonValue

from smartkeeper.contracts import (
    ActionItem,
    Adjudication,
    GameConfig,
    Intent,
    Opening,
    Outcome,
    RulePack,
    Sheet,
    SheetSubmission,
)
from smartkeeper.dice import DiceRoller, SeededRandomSource
from smartkeeper.engine import Engine
from smartkeeper.eventlog import SqlEventLog
from smartkeeper.handles import SqlHandleStore
from smartkeeper.memory import SqlMemoryStore
from smartkeeper.rounds import RoundStateMachine
from smartkeeper.rules import RulesService, SqlRulePackStore
from smartkeeper.spatial import ShapelySpatial
from smartkeeper.world import WorldService
from tests.fixtures import load_pack
from tests.fixtures.maps import small_map

SCENARIO_PUBLIC = """---
start_time: "2030-01-01T20:00"
---
A quiet town. Something is wrong.
"""

SCENARIO_KP = """---
npcs:
  - id: npc_1
    template: {npc_template}
    sheet: {npc_sheet}
    location: {{pos: {{x: -50, y: 150, z: 0}}}}
---
The baker did it.
"""


class MemoryMapStore:
    def __init__(self) -> None:
        self.maps = {"small": small_map()}

    def load(self, map_id: str):
        from smartkeeper.contracts import NotFound

        if map_id not in self.maps:
            raise NotFound("map.not_found", id=map_id)
        return self.maps[map_id]

    def list_ids(self) -> list[str]:
        return sorted(self.maps)

    def save(self, map_id: str, text: str):
        raise NotImplementedError


def make_db() -> sa.Engine:
    """临时文件上的 SQLite（WAL）。不用共享单连接的内存库：多线程写反馈草稿时会互相回滚。"""
    import tempfile

    from sqlalchemy import event

    fd, path = tempfile.mkstemp(suffix=".db", prefix="sk-test-")
    import os

    os.close(fd)
    db = sa.create_engine(
        f"sqlite:///{path}", connect_args={"check_same_thread": False, "timeout": 30}
    )

    @event.listens_for(db, "connect")
    def _pragmas(conn, _rec):  # type: ignore[no-untyped-def]
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()

    return db


def make_engine(seed: int = 1, db: sa.Engine | None = None) -> tuple[Engine, SqlRulePackStore]:
    db = db or make_db()
    dice = DiceRoller(SeededRandomSource(seed))
    rules = RulesService()
    packs = SqlRulePackStore(db, rules)
    engine = Engine(
        db=db,
        events=SqlEventLog(db),
        packs=packs,
        rules=rules,
        world=WorldService(rules),
        rounds=RoundStateMachine(),
        dice=dice,
        maps=MemoryMapStore(),
        spatial=ShapelySpatial(),
        handles=SqlHandleStore(db),
        memory=SqlMemoryStore(db),
    )
    return engine, packs


def sheets_for(pack: RulePack, i: int) -> list[SheetSubmission]:
    """按规则包的 player_entities 为第 i 个玩家造角色卡：每个模板取最少数量，内容取自例题。"""
    out: list[SheetSubmission] = []
    for pe in pack.player_entities:
        sample = next(s for s in pack.samples if s.template == pe.template)
        for k in range(max(pe.min, 1)):
            raw = dict(sample.sheet)
            raw["name"] = f"P{i}-{pe.template}-{k}"
            out.append(SheetSubmission(template=pe.template, sheet=Sheet.model_validate(raw)))
    return out


@dataclass
class Table:
    engine: Engine
    packs: SqlRulePackStore
    pack: RulePack
    pack_id: str
    game_id: str
    players: list[str]
    tokens: dict[str, str] = field(default_factory=dict[str, str])

    def entities(self, pid: str) -> list[str]:
        return self.engine.controlled(self.game_id, pid)

    def declare_all(self, players: list[str] | None = None) -> None:
        for pid in players if players is not None else self.players:
            ent = self.entities(pid)[0]
            intent = Intent(items=(ActionItem(actor=ent, verb="look around"),))
            self.engine.declare_action(pid, "I look around.", intent)

    def simple_adjudication(self, minutes: int = 30, **extra: object) -> Adjudication:
        r = self.engine.round(self.game_id)
        decl = self.engine.declarations(self.game_id)
        outcomes: list[Outcome] = []
        for pid in self.engine.required_players(self.game_id):
            resolves: tuple[str, ...] = ()
            if pid in decl and (not r.forced or pid in r.submitted):
                intent = Intent.model_validate(decl[pid].payload["intent"])
                resolves = tuple(it.id for it in intent.items if it.id)
            outcomes.append(Outcome(player_id=pid, resolves=resolves, result="nothing happens"))
        body: dict[str, object] = {"time_advance_minutes": minutes, "outcomes": outcomes, **extra}
        return Adjudication.model_validate(body)

    def play_round(self, adj: Adjudication | None = None, forced: bool = False) -> None:
        e = self.engine
        e.close_round(self.game_id, forced=forced)
        adj = adj or self.simple_adjudication()
        e.apply_adjudication(self.game_id, adj)
        for o in adj.outcomes:
            e.set_feedback_draft(self.game_id, o.player_id, f"feedback for {o.player_id}")
        if adj.public_events:
            e.set_broadcast_draft(self.game_id, "public news")
        e.publish_round(self.game_id)


def setup_table(
    pack_name: str, n_players: int, seed: int = 1, map_id: str | None = "small"
) -> Table:
    engine, packs = make_engine(seed)
    pack = load_pack(pack_name)
    pack_id = packs.create_pack(pack.world.name)
    packs.save_version(pack_id, pack)
    npc_tpl = pack.templates[-1].name
    npc_sample = next(s for s in pack.samples if s.template == npc_tpl)
    import json

    npc_sheet: JsonValue = dict(npc_sample.sheet)
    scenario_kp = SCENARIO_KP.format(npc_template=npc_tpl, npc_sheet=json.dumps(npc_sheet))
    game = engine.create_game(
        GameConfig(
            name="t",
            rulepack_id=pack_id,
            rulepack_version=1,
            map_id=map_id,
            scenario_public=SCENARIO_PUBLIC,
            scenario_kp=scenario_kp,
        )
    )
    players: list[str] = []
    tokens: dict[str, str] = {}
    for i in range(n_players):
        p, token = engine.add_player(game.id, f"player {i}")
        players.append(p.id)
        tokens[p.id] = token
        engine.submit_character(p.id, sheets_for(pack, i))
        engine.approve_character(p.id)
    t = Table(engine, packs, pack, pack_id, game.id, players, tokens)
    positions = {
        e: {"pos": {"x": float(i * 2 - 50), "y": -40.0, "z": 0.0}}
        for i, pid in enumerate(players)
        for e in t.entities(pid)
    }
    opening = Opening.model_validate(
        {
            "broadcast": "It begins.",
            "messages": {pid: f"secret for {pid}" for pid in players},
            "positions": positions,
        }
    )
    engine.start_game(game.id, opening)
    return t
