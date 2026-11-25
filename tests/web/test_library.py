"""角色库：按规则书存的角色，和局分开；设了密码的查看、使用、修改都要密码；剧本属于规则书。"""

from __future__ import annotations

import json
from pathlib import Path

from smartkeeper.engine import public_meta
from tests.web.conftest import Site
from tests.web.test_lobby import new_game

ROOT = Path(__file__).resolve().parents[2]


def sample() -> list[dict[str, object]]:
    pack = json.loads((ROOT / "tests/fixtures/rulepack_single.json").read_text(encoding="utf-8"))[
        "pack"
    ]
    return [{"template": s["template"], "sheet": s["sheet"]} for s in pack["samples"][:1]]


def test_characters_are_shared_within_a_rulebook_and_guarded_by_a_password(site: Site) -> None:
    g1 = new_game(site, "one")
    first = site.admin.get(f"/api/admin/games/{g1}").json()["game"]
    g2 = site.admin.post(  # 同一套规则书的另一局
        "/api/admin/games",
        json={
            "name": "two",
            "rulepack_id": first["rulepack_id"],
            "rulepack_version": first["rulepack_version"],
            "map_id": "demo_shibuya",
            "scenario": "demo",
        },
    ).json()["id"]
    alice, bob = site.client(), site.client()
    alice.post("/api/lobby/join", json={"game_id": g1, "name": "Alice"})
    bob.post("/api/lobby/join", json={"game_id": g2, "name": "Bob"})
    sheets = sample()
    open_one = alice.post("/api/library", json={"sheets": sheets, "summary": "谁都能用"}).json()
    locked = alice.post(
        "/api/library", json={"sheets": sheets, "name": "秘密", "password": "pw"}
    ).json()
    assert open_one["name"] and not open_one["locked"] and locked["locked"]
    assert open_one["created_by"] == "Alice"
    # 别的局、别的玩家也看得到（同一套规则书），设了密码的要密码才能打开
    listed = {c["id"]: c for c in bob.get("/api/library").json()}
    assert set(listed) >= {open_one["id"], locked["id"]}
    assert bob.post(f"/api/library/{open_one['id']}/open", json={}).json()["sheets"] == sheets
    r = bob.post(f"/api/library/{locked['id']}/open", json={"password": "nope"})
    assert r.json()["detail"]["code"] == "library.bad_password"
    assert bob.post(f"/api/library/{locked['id']}/open", json={"password": "pw"}).status_code == 200
    # 修改要原来的密码；可以去掉密码
    r = bob.put(f"/api/library/{locked['id']}", json={"sheets": sheets, "name": "改名"})
    assert r.json()["detail"]["code"] == "library.bad_password"
    r = bob.put(
        f"/api/library/{locked['id']}",
        json={"sheets": sheets, "name": "改名", "password": "pw", "new_password": ""},
    ).json()
    assert r["name"] == "改名" and not r["locked"]


def test_scenario_must_belong_to_the_rulebook(site: Site) -> None:
    a = site.admin
    text = (ROOT / "tests/fixtures/rulepack_single.json").read_text(encoding="utf-8")
    v = a.post("/api/admin/rulepacks/import", json={"text": text}).json()
    mats = a.get("/api/admin/materials").json()
    book = public_meta(
        (ROOT / "scenarios/grail_shibuya/scenario_public.md").read_text(encoding="utf-8")
    ).rulebook
    assert book and mats["scenario_rulebooks"]["grail_shibuya"] == book
    r = a.post(
        "/api/admin/games",
        json={
            "name": "wrong",
            "rulepack_id": v["pack_id"],
            "rulepack_version": v["version"],
            "map_id": "demo_shibuya",
            "scenario": "grail_shibuya",
        },
    )
    assert r.json()["detail"]["code"] == "game.scenario_other_rulebook"
