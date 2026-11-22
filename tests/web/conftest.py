from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from smartkeeper.web.app import Settings, build_services, create_app
from smartkeeper.web.auth import hash_password
from smartkeeper.web.services import Services

ROOT = Path(__file__).resolve().parents[2]
PASSWORD = "correct horse battery staple"


@dataclass
class Site:
    services: Services
    settings: Settings
    admin: TestClient

    def client(self) -> TestClient:
        return TestClient(create_app(self.settings, self.services))


@pytest.fixture
def site(tmp_path: Path) -> Site:
    settings = Settings(
        db_path=str(tmp_path / "web.db"),
        maps_dir=str(ROOT / "maps"),
        scenarios_dir=str(ROOT / "scenarios"),
        static_dir=str(tmp_path / "no-static"),
        admin_password_hash=hash_password(PASSWORD),
        session_secret="test-secret",
        judge_provider="fake",
        writer_provider="fake",
        base_url="http://testserver",
    )
    services = build_services(settings)
    admin = TestClient(create_app(settings, services))
    assert admin.post("/api/admin/login", json={"password": PASSWORD}).status_code == 200
    return Site(services, settings, admin)


def setup_game(site: Site, n_players: int = 2) -> tuple[str, list[TestClient]]:
    """管理员：导入规则包、建局、发邀请。玩家：打开邀请链接、抽身份、建角。返回局 id 和各玩家的客户端。"""
    a = site.admin
    text = (ROOT / "tests/fixtures/rulepack_single.json").read_text(encoding="utf-8")
    v = a.post("/api/admin/rulepacks/import", json={"text": text}).json()
    g = a.post(
        "/api/admin/games",
        json={
            "name": "t",
            "rulepack_id": v["pack_id"],
            "rulepack_version": v["version"],
            "map_id": "demo_shibuya",
            "scenario": "demo",
        },
    ).json()
    players: list[TestClient] = []
    import json

    sample = json.loads(text)["pack"]["samples"][0]["sheet"]
    for i in range(n_players):
        url = a.post(f"/api/admin/games/{g['id']}/invites", json={"display_name": f"P{i}"}).json()[
            "url"
        ]
        c = site.client()
        r = c.get(url.replace("http://testserver", ""), follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/join"
        assert c.post("/api/identity", json={}).status_code == 200
        sheet = {**sample, "name": f"Hero {i}"}
        assert (
            c.post(
                "/api/character", json={"sheets": [{"template": "person", "sheet": sheet}]}
            ).status_code
            == 200
        )
        players.append(c)
    return g["id"], players
