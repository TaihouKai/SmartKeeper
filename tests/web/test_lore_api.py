"""规则书页面上的资料库：规则书总览、自己所在的局、房间列表三个入口都能查；关着的条目不给；没有资料库的条数是 0。"""

from __future__ import annotations

import json
from pathlib import Path

from tests.web.conftest import ROOT, Site, setup_game


def test_lore_is_browsable_from_every_rulebook_page(site: Site) -> None:
    a = site.admin
    raw = json.loads((ROOT / "tests/fixtures/rulepack_single.json").read_text(encoding="utf-8"))
    raw["pack"]["lore"] = [
        {"title": "教会", "keys": ["圣堂教会"], "content": "一个古老的宗教组织。"},
        {"title": "关着的", "keys": ["秘密"], "content": "不该出现。", "disabled": True},
    ]
    book = a.post("/api/admin/rulepacks/import", json={"text": json.dumps(raw)}).json()["pack_id"]
    visitor = site.client()
    assert visitor.get(f"/api/books/{book}").json()["lore_count"] == 1
    assert [x["title"] for x in visitor.get(f"/api/books/{book}/lore").json()] == ["教会"]
    # 没有资料库的规则书：条数 0，页面上不出按钮
    plain = a.post(
        "/api/admin/rulepacks/import",
        json={
            "text": Path(ROOT / "tests/fixtures/rulepack_single.json").read_text(encoding="utf-8")
        },
    ).json()["pack_id"]
    assert visitor.get(f"/api/books/{plain}").json()["lore_count"] == 0
    # 局里：玩家按座位查；没加入的从房间列表查
    gid, (p0, *_rest) = setup_game(site, 1)
    pack_id = a.get(f"/api/admin/games/{gid}").json()["game"]["rulepack_id"]
    assert pack_id != book  # setup_game 导入的是没有资料库的规则书
    assert p0.get("/api/rules").json()["lore_count"] == 0 and p0.get("/api/rules/lore").json() == []
    assert visitor.get(f"/api/lobby/{gid}/rulebook").json()["lore_count"] == 0
    assert visitor.get(f"/api/lobby/{gid}/lore").json() == []
