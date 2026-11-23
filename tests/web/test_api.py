from __future__ import annotations

import re

from smartkeeper.web.auth import ADMIN_COOKIE
from tests.web.conftest import Site, setup_game


def start(site: Site, game_id: str) -> None:
    r = site.admin.patch(f"/api/admin/games/{game_id}", json={"action": "start"})
    assert r.status_code == 200, r.text
    assert site.admin.get(f"/api/admin/games/{game_id}").json()["game"]["status"] == "running"


def test_player_token_gets_403_on_every_admin_route(site: Site) -> None:
    _, (p1, _) = setup_game(site)
    checked = 0
    paths = p1.app.openapi()["paths"]  # type: ignore[attr-defined]
    for raw_path, ops in paths.items():
        if not raw_path.startswith("/api/admin"):
            continue
        if raw_path in ("/api/admin/login", "/api/admin/logout", "/api/admin/enabled"):
            continue
        path = re.sub(r"\{[^}]+\}", "x", raw_path)
        for method in ops:
            r = p1.request(method, path, json={})
            assert r.status_code == 403, (method, path, r.status_code)
            checked += 1
    assert checked > 20
    # 用 Bearer 也一样
    token = p1.cookies.get("sk_player")
    r = site.client().get("/api/admin/games", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_bad_admin_password(site: Site) -> None:
    c = site.client()
    assert c.post("/api/admin/login", json={"password": "nope"}).status_code == 403
    assert c.get("/api/admin/games").status_code == 403


def test_admin_session_does_not_change_player_responses(site: Site) -> None:
    game_id, (p1, _p2) = setup_game(site)
    start(site, game_id)
    both = site.client()
    both.cookies.set("sk_player", p1.cookies.get("sk_player") or "")
    both.cookies.set(ADMIN_COOKIE, site.admin.cookies.get(ADMIN_COOKIE) or "", path="/api/admin")
    for path in (
        "/api/me",
        "/api/events",
        "/api/status",
        "/api/rules",
        "/api/scene",
        "/api/sheets",
        "/api/chat",
        "/api/chat/peers",
        "/api/map",
    ):
        a, b = p1.get(path), both.get(path)
        assert a.status_code == 200, path
        assert a.content == b.content, path


def test_unattended_round_resolves_and_publishes(site: Site) -> None:
    game_id, players = setup_game(site, 3)
    start(site, game_id)
    for round_no in (1, 2):
        for c in players:
            echo = c.post("/api/action/parse", json={"text": "我四处看看"}).json()
            assert echo["items"] and not echo["unresolved"]
            r = c.post("/api/action", json={"parse_id": echo["parse_id"]})
            assert r.status_code == 200, r.text
        status = players[0].get("/api/status").json()
        assert status["me"] == "act"
        assert "round" not in status  # 玩家看不到回合数
        assert status["game_seconds"] == 60 * round_no
        for c in players:
            fb = [e for e in c.get("/api/events").json() if e["type"] == "feedback"]
            assert len(fb) == round_no
            assert all(e["round_no"] == 0 for e in c.get("/api/events").json())


def test_player_never_sees_entity_ids(site: Site) -> None:
    game_id, (p1, _p2) = setup_game(site)
    start(site, game_id)
    echo = p1.post("/api/action/parse", json={"text": "看看"}).json()
    p1.post("/api/action", json={"parse_id": echo["parse_id"]})
    for path in ("/api/events", "/api/scene", "/api/sheets"):
        body = p1.get(path).text
        assert "ent_" not in body and "npc_" not in body, path


def test_chat_canary_never_reaches_llm_or_admin_log(site: Site) -> None:
    game_id, (p1, p2) = setup_game(site)
    start(site, game_id)
    peer = p1.get("/api/chat/peers").json()[0]["player_id"]
    canary = "CHAT_CANARY_7731"
    assert p1.post("/api/chat", json={"to": peer, "text": f"秘密 {canary}"}).status_code == 200
    assert canary in p2.get("/api/chat").text
    for c in (p1, p2):
        echo = c.post("/api/action/parse", json={"text": "看看"}).json()
        c.post("/api/action", json={"parse_id": echo["parse_id"]})
    s = site.services
    for call in s.llm_log.list(game_id, 1000):
        assert canary not in call.system and canary not in str(call.messages)
    assert canary not in site.admin.get(f"/api/admin/games/{game_id}/events").text


def test_kp_chat_and_broadcast(site: Site) -> None:
    game_id, (p1, p2) = setup_game(site)
    start(site, game_id)
    assert p1.post("/api/kp/chat", json={"text": "这里是哪"}).status_code == 200
    replies = [
        e for e in p1.get("/api/events").json() if e["type"] == "pm_kp" and e["actor"] == "kp"
    ]
    assert any("脚本化" in str(e["payload"]["text"]) for e in replies)
    assert p1.post("/api/broadcast", json={"text": "大家好", "anonymous": True}).status_code == 200
    seen = [
        e
        for e in p2.get("/api/events").json()
        if e["type"] == "broadcast" and e["payload"]["text"] == "大家好"
    ]
    assert seen[0]["actor"] == "anonymous" and seen[0]["actor_name"] is None


def test_errors_are_codes(site: Site) -> None:
    _game_id, (p1, _) = setup_game(site)
    r = p1.post("/api/broadcast", json={"text": ""})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "text.empty"


def test_invalid_invite_redirects(site: Site) -> None:
    r = site.client().get("/join/not-a-token", follow_redirects=False)
    assert r.headers["location"] == "/join?invalid=1"
    assert site.client().get("/api/me").status_code == 401
