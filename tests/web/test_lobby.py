"""房间列表：不用邀请链接，填名字直接加入；一个浏览器可以在几局里各有一个座位，用“继续”切换。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from tests.web.conftest import Site

ROOT = Path(__file__).resolve().parents[2]


def new_game(site: Site, name: str) -> str:
    a = site.admin
    text = (ROOT / "tests/fixtures/rulepack_single.json").read_text(encoding="utf-8")
    v = a.post("/api/admin/rulepacks/import", json={"text": text}).json()
    g = a.post(
        "/api/admin/games",
        json={
            "name": name,
            "rulepack_id": v["pack_id"],
            "rulepack_version": v["version"],
            "map_id": "demo_shibuya",
            "scenario": "demo",
        },
    ).json()
    return str(g["id"])


def rooms(c: TestClient) -> dict[str, dict[str, object]]:
    r = c.get("/api/lobby")
    assert r.status_code == 200
    return {g["id"]: g for g in r.json()}


def test_anyone_can_join_from_the_room_list(site: Site) -> None:
    gid = new_game(site, "first")
    c = site.client()
    assert c.get("/api/me").status_code == 401
    room = rooms(c)[gid]
    assert room["joinable"] is True and room["seat"] is None and room["players"] == 0
    r = c.post("/api/lobby/join", json={"game_id": gid, "name": "Alice"})
    assert r.status_code == 200
    assert "/join/" in r.json()["link"]
    me = c.get("/api/me").json()
    assert me["game_id"] == gid and me["display_name"] == "Alice"
    room = rooms(c)[gid]
    assert room["seat"] == "Alice" and room["active"] is True and room["players"] == 1
    # 同一个浏览器不能再加入一次；别人不能重名
    assert c.post("/api/lobby/join", json={"game_id": gid, "name": "Bob"}).json()["detail"][
        "code"
    ] == ("lobby.already_in")
    other = site.client()
    r = other.post("/api/lobby/join", json={"game_id": gid, "name": "Alice"})
    assert r.json()["detail"]["code"] == "lobby.name_taken"
    # 个人链接在别的浏览器里也能回到这一局
    third = site.client()
    link = c.post("/api/lobby/enter", json={"game_id": gid}).json()["link"]
    third.get(link.replace("http://testserver", ""), follow_redirects=False)
    assert third.get("/api/me").json()["display_name"] == "Alice"


def test_one_browser_switches_between_its_games(site: Site) -> None:
    g1, g2 = new_game(site, "one"), new_game(site, "two")
    c = site.client()
    assert c.post("/api/lobby/join", json={"game_id": g1, "name": "A"}).status_code == 200
    assert c.post("/api/lobby/join", json={"game_id": g2, "name": "B"}).status_code == 200
    assert c.get("/api/me").json()["game_id"] == g2
    assert c.post("/api/lobby/enter", json={"game_id": g1}).status_code == 200
    assert c.get("/api/me").json()["game_id"] == g1
    listed = rooms(c)
    assert listed[g1]["active"] is True and listed[g2]["seat"] == "B"
    assert site.client().post("/api/lobby/enter", json={"game_id": g1}).status_code == 404


def test_closed_and_ended_games_are_not_listed(site: Site) -> None:
    gid = new_game(site, "closed")
    game = site.admin.get(f"/api/admin/games/{gid}").json()
    settings = {**game["game"]["settings"], "lobby": False}
    assert (
        site.admin.patch(f"/api/admin/games/{gid}", json={"settings": settings}).status_code == 200
    )
    c = site.client()
    assert gid not in rooms(c)
    assert c.post("/api/lobby/join", json={"game_id": gid, "name": "X"}).status_code == 403
    gid2 = new_game(site, "ended")
    site.services.engine.end_game(gid2)
    assert gid2 not in rooms(c)
