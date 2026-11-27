"""kp 测试的装配：FakeLLM 加内存 engine（各模块的真实实现、内存 SQLite）。"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from smartkeeper.contracts import Intent, Outcome, RulePack, SheetSubmission
from smartkeeper.engine import Engine
from smartkeeper.kp import KP, KPConfig, fixed_models
from smartkeeper.llm import FakeCall, FakeLLM
from tests.engine.harness import make_engine, sheets_for
from tests.fixtures import load_pack

ROOT = Path(__file__).resolve().parents[2]
SCENARIO = ROOT / "scenarios" / "demo"


@dataclass
class Game:
    engine: Engine
    kp: KP
    llm: FakeLLM
    game_id: str
    players: list[str]
    round_hooks: dict[int, dict[str, Any]] = field(default_factory=dict[int, dict[str, Any]])
    # KP 出错后排上的自动重试（不真的等）：(多少秒以后, 要做的事)
    scheduled: list[tuple[float, Callable[[], None]]] = field(
        default_factory=list[tuple[float, Callable[[], None]]]
    )

    def ents(self, pid: str) -> list[str]:
        return self.engine.controlled(self.game_id, pid)

    def own_ref(self, pid: str) -> str:
        return self.engine.scene(self.game_id, pid).entities[0].ref

    def declare(self, pid: str, text: str = "我四处看看。") -> None:
        intent = self.kp.parse_intent(pid, text)
        self.engine.declare_action(pid, text, intent)
        self.kp.on_action(self.game_id)

    def play_round(self, texts: dict[str, str] | None = None) -> None:
        for pid in self.players:
            self.declare(pid, (texts or {}).get(pid, "我四处看看。"))


def install_handlers(g: Game) -> None:
    e, llm = g.engine, g.llm
    counter = {"n": 0}

    def review(call: FakeCall) -> str:
        return json.dumps({"approved": True, "comments": "ok"})

    def opening(call: FakeCall) -> str:
        players = [p.id for p in e.players(g.game_id)]
        state = e.world_state(g.game_id)
        ents = state["entities"]
        assert isinstance(ents, dict)
        need = [k for k, v in ents.items() if isinstance(v, dict) and v.get("pos") is None]
        return json.dumps(
            {
                "broadcast": "大屏幕黑了几秒。",
                "messages": {p: f"你的开场信息 {p}" for p in players},
                "positions": {
                    k: {"pos": {"x": -40 + i, "y": -60, "z": 0}, "inside": None}
                    for i, k in enumerate(need)
                },
            },
            ensure_ascii=False,
        )

    def name(call: FakeCall) -> str:
        counter["n"] += 1
        return json.dumps({"label": f"人{counter['n']}"}, ensure_ascii=False)

    def intent(call: FakeCall) -> str:
        m = re.search(r'"ref": "(h[0-9a-f]+)",\s*"name"', call.prompt)
        assert m, call.prompt
        return json.dumps(
            {
                "items": [
                    {
                        "actor": m.group(1),
                        "verb": "look",
                        "targets": [],
                        "detail": "",
                        "seconds": 600,
                    }
                ]
            }
        )

    def plan(call: FakeCall) -> str:
        decl = e.declarations(g.game_id)
        checks = []
        for ev in decl.values():
            it = Intent.model_validate(ev.payload["intent"]).items[0]
            checks.append({"entity": it.actor, "check": "spot", "against": None, "reason": "look"})
        return json.dumps({"checks": checks, "queries": []})

    def adjudicate(call: FakeCall) -> str:
        r = e.round(g.game_id)
        acts = e.activities(g.game_id)
        outcomes = []
        for p in e.players(g.game_id):
            ents = e.controlled(g.game_id, p.id)
            if not p.active or not ents:
                continue
            resolves = [st.item for x in ents if x in acts for st in acts[x].steps]
            outcomes.append(
                Outcome(
                    player_id=p.id,
                    resolves=tuple(resolves),
                    result="你看见了 {{npc_thief}} 匆匆走过。",
                ).model_dump()
            )
        body: dict[str, Any] = {"outcomes": outcomes}
        body.update(g.round_hooks.get(r.no, {}))
        return json.dumps(body, ensure_ascii=False)

    llm.on("review_character", review)
    llm.on("opening", opening)
    llm.on("name_handle", name)
    llm.on("parse_intent", intent)
    llm.on("claim_check", lambda c: json.dumps({"verdict": "holds", "evidence": [], "note": "ok"}))
    llm.on("plan", plan)
    llm.on("adjudicate", adjudicate)
    llm.on("feedback", lambda c: "你的反馈。")
    llm.on("broadcast", lambda c: "公共消息。")
    llm.on("chat", lambda c: "KP 的回答。")
    llm.on("leak_check", lambda c: '{"leaks": []}')
    llm.on("summary", lambda c: "摘要。")


def new_game(
    n_players: int = 3,
    *,
    scenario_kp_extra: str = "",
    config: KPConfig | None = None,
    llm: FakeLLM | None = None,
    engine: Engine | None = None,
    pack: RulePack | None = None,
    start: bool = True,
) -> Game:
    from smartkeeper.contracts import GameConfig

    pack = pack or load_pack("single")
    if engine is None:
        engine, packs = make_engine(seed=7)
        pack_id = packs.create_pack(pack.world.name)
        packs.save_version(pack_id, pack)
    else:
        pack_id = engine.list_games()[0].rulepack_id if engine.list_games() else ""
    llm = llm or FakeLLM()
    scheduled: list[tuple[float, Callable[[], None]]] = []
    kp = KP(
        engine,
        fixed_models(llm, "fake-judge", llm, "fake-writer"),
        config or KPConfig(),
        # 出错后的自动重试：测试里不真的等，记下来由测试自己决定要不要执行
        schedule=lambda delay, fn: scheduled.append((delay, fn)),
    )
    game = engine.create_game(
        GameConfig(
            name="demo",
            rulepack_id=pack_id,
            rulepack_version=1,
            map_id="small",
            scenario_public=(SCENARIO / "scenario_public.md").read_text(encoding="utf-8"),
            scenario_kp=(SCENARIO / "scenario_kp.md").read_text(encoding="utf-8")
            + scenario_kp_extra,
        )
    )
    g = Game(engine, kp, llm, game.id, [], scheduled=scheduled)
    install_handlers(g)
    for i in range(n_players):
        p, _ = engine.add_player(game.id, f"玩家{i}")
        g.players.append(p.id)
        engine.assign_identity(p.id)
        subs: list[SheetSubmission] = sheets_for(pack, i)
        engine.submit_character(p.id, subs)
        kp.review_character(p.id)
    if start:
        kp.open_game(game.id)
    return g
