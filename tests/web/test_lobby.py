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


def test_each_game_page_names_its_game(site: Site) -> None:
    """每一局自己的网址：请求头带上局 id，就用这个浏览器在那一局的座位，不管“当前在玩”的是哪一局。"""
    g1, g2 = new_game(site, "one"), new_game(site, "two")
    c = site.client()
    assert c.post("/api/lobby/join", json={"game_id": g1, "name": "A"}).status_code == 200
    assert c.post("/api/lobby/join", json={"game_id": g2, "name": "B"}).status_code == 200
    assert c.get("/api/me").json()["game_id"] == g2  # 当前在玩的是后加入的那一局
    assert c.get("/api/me", headers={"X-SK-Game": g1}).json()["display_name"] == "A"
    assert c.get("/api/me", headers={"X-SK-Game": g2}).json()["display_name"] == "B"
    # 没在那一局有座位：不能冒用别的座位
    g3 = new_game(site, "three")
    r = c.get("/api/me", headers={"X-SK-Game": g3})
    assert r.status_code == 401
    # 邀请链接把人带到那一局自己的网址
    link = c.post("/api/lobby/enter", json={"game_id": g1}).json()["link"]
    r = site.client().get(link.replace("http://testserver", ""), follow_redirects=False)
    assert r.headers["location"] == f"/g/{g1}"


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


def test_players_rename_themselves_and_names_stay_unique(site: Site) -> None:
    gid = new_game(site, "names")
    a, b = site.client(), site.client()
    a.post("/api/lobby/join", json={"game_id": gid, "name": "A"})
    b.post("/api/lobby/join", json={"game_id": gid, "name": "B"})
    assert a.post("/api/me/name", json={"name": "Alice"}).status_code == 200
    assert a.get("/api/me").json()["display_name"] == "Alice"
    assert (
        b.post("/api/me/name", json={"name": "Alice"}).json()["detail"]["code"]
        == "lobby.name_taken"
    )
    assert b.post("/api/me/name", json={"name": "  "}).json()["detail"]["code"] == "player.bad_name"


def test_character_form_draft_is_kept_on_the_server(site: Site) -> None:
    gid = new_game(site, "draft")
    c = site.client()
    c.post("/api/lobby/join", json={"game_id": gid, "name": "A"})
    assert c.get("/api/character/draft").json() == {"sheets": None, "updated_at": None}
    draft = [
        {"template": "person", "sheet": {"name": "half done", "fields": {"str": ""}, "groups": {}}}
    ]
    r = c.put("/api/character/draft", json={"sheets": draft})
    assert r.status_code == 200 and r.json()["updated_at"]
    # 另一个浏览器用个人链接进来，接着改
    link = c.post("/api/lobby/enter", json={"game_id": gid}).json()["link"]
    other = site.client()
    other.get(link.replace("http://testserver", ""), follow_redirects=False)
    assert other.get("/api/character/draft").json()["sheets"] == draft
    assert c.put("/api/character/draft", json={"sheets": "x" * 600_000}).status_code == 422


def test_an_old_page_cannot_overwrite_a_newer_draft(site: Site) -> None:
    """两个页面编辑同一张卡：旧页面（基于旧的保存时间）存不进去，也就不会拿旧内容去提交。"""
    gid = new_game(site, "stale")
    c = site.client()
    c.post("/api/lobby/join", json={"game_id": gid, "name": "A"})
    v1 = [{"template": "person", "sheet": {"name": "v1", "fields": {}, "groups": {}}}]
    v2 = [{"template": "person", "sheet": {"name": "v2", "fields": {}, "groups": {}}}]
    first = c.put("/api/character/draft", json={"sheets": v1, "base": ""}).json()["updated_at"]
    # 新页面基于 first 存了 v2；还停在“没有草稿”时打开的旧页面再存，被拒绝
    second = c.put("/api/character/draft", json={"sheets": v2, "base": first}).json()["updated_at"]
    r = c.put("/api/character/draft", json={"sheets": v1, "base": ""})
    assert r.json()["detail"]["code"] == "character.draft_stale"
    r = c.put("/api/character/draft", json={"sheets": v1, "base": first})
    assert r.json()["detail"]["code"] == "character.draft_stale"
    assert c.get("/api/character/draft").json()["sheets"] == v2
    ok = c.put("/api/character/draft", json={"sheets": v2, "base": second})
    assert ok.status_code == 200


def test_rulebook_of_a_listed_game_is_public(site: Site) -> None:
    gid = new_game(site, "book")
    r = site.client().get(f"/api/lobby/{gid}/rulebook")
    assert r.status_code == 200 and r.json()["game_name"] == "book"
    assert site.client().get("/api/lobby/nope/rulebook").status_code == 404


def test_preview_shows_values_even_when_something_else_is_unfinished(site: Site) -> None:
    """建卡预览：别处还没填完（例如一条技能没写名字），算得出来的数值照样给。"""
    gid = new_game(site, "preview")
    c = site.client()
    c.post("/api/lobby/join", json={"game_id": gid, "name": "Pat"})
    text = (ROOT / "tests/fixtures/rulepack_single.json").read_text(encoding="utf-8")
    import json

    sample = json.loads(text)["pack"]["samples"][0]["sheet"]
    sheet = {**sample, "groups": {"skills": [{"name": "", "fields": {}}]}}
    r = c.post("/api/character/preview", json={"template": "person", "sheet": sheet}).json()
    assert r["problems"]
    assert any(d["name"] == "hp_max" for d in r["derived"])
