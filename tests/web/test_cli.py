"""命令行演示的装配路径：用 FakeLLM 代替真模型跑一遍，确保真模型那一步只差 API key。"""

from __future__ import annotations

import json
import re
from pathlib import Path

from smartkeeper.contracts import Intent, Outcome
from smartkeeper.llm import FakeCall, FakeLLM
from smartkeeper.web.app import Settings, build_services
from smartkeeper.web.cli import run_demo

ROOT = Path(__file__).resolve().parents[2]


def test_cli_demo_with_fake_llm(tmp_path: Path) -> None:
    fake = FakeLLM()
    s = build_services(
        Settings(db_path=str(tmp_path / "t.db"), maps_dir=str(ROOT / "maps")),
        judge=fake,
        writer=fake,
    )
    e = s.engine

    def gid() -> str:
        return e.list_games()[-1].id

    def opening(c: FakeCall) -> str:
        ps = [p.id for p in e.players(gid())]
        return json.dumps({"broadcast": "b", "messages": {p: "m" for p in ps}, "positions": {}})

    def intent(c: FakeCall) -> str:
        m = re.search(r'"ref": "(h[0-9a-f]+)",\s*"name"', c.prompt)
        assert m
        return json.dumps({"items": [{"actor": m.group(1), "verb": "look"}]})

    def adjudicate(c: FakeCall) -> str:
        d = e.declarations(gid())
        outs = [
            Outcome(
                player_id=p,
                resolves=tuple(
                    i.id or "" for i in Intent.model_validate(d[p].payload["intent"]).items
                ),
                result="ok",
            ).model_dump()
            for p in e.required_players(gid())
        ]
        return json.dumps({"time_advance_minutes": 5, "outcomes": outs})

    fake.on("review_character", lambda c: '{"approved": true, "comments": ""}')
    fake.on("opening", opening)
    fake.on("name_handle", lambda c: '{"label": "x"}')
    fake.on("parse_intent", intent)
    fake.on("plan", lambda c: '{"checks": [], "queries": []}')
    fake.on("adjudicate", adjudicate)
    fake.on("feedback", lambda c: "fb")
    game_id = run_demo(
        s,
        rulepack_text=(ROOT / "tests/fixtures/rulepack_single.json").read_text(encoding="utf-8"),
        map_id="demo_shibuya",
        scenario_dir=ROOT / "scenarios/demo",
        players=2,
        rounds=1,
    )
    assert e.round(game_id, 1).status == "published"
    calls = s.llm_log.list(game_id)
    assert calls and all(c.valid is not False for c in calls)
