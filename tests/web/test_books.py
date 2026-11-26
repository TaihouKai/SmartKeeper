"""规则书总览：和对局列表分开。每套规则书下面是它的剧本和角色库；不进局也能建、改、删角色。"""

from __future__ import annotations

import json
from pathlib import Path

from tests.web.conftest import Site
from tests.web.test_library import sample

ROOT = Path(__file__).resolve().parents[2]


def import_pack(site: Site, path: str) -> str:
    text = (ROOT / path).read_text(encoding="utf-8")
    return str(
        site.admin.post("/api/admin/rulepacks/import", json={"text": text}).json()["pack_id"]
    )


def test_books_list_their_scenarios_and_characters_without_a_game(site: Site) -> None:
    book = import_pack(site, "rulepacks/grail/pack.json")
    other = import_pack(site, "tests/fixtures/rulepack_single.json")
    visitor = site.client()  # 没加入任何一局
    listed = {b["id"]: b for b in visitor.get("/api/books").json()}
    assert {book, other} <= set(listed)
    # 剧本按开头写的规则书归属：只出现在那套规则书下
    detail = visitor.get(f"/api/books/{book}").json()
    assert "grail_shibuya" in [x["id"] for x in detail["scenario_list"]]
    assert detail["handbook"]
    assert "grail_shibuya" not in [
        x["id"] for x in visitor.get(f"/api/books/{other}").json()["scenario_list"]
    ]
    scen = visitor.get(f"/api/books/{book}/scenarios/grail_shibuya").json()
    assert scen["title"] and not scen["text"].startswith("---")
    # 建卡表单要的规则、预览、公式检查都按规则书来，不用进局
    form = visitor.get(f"/api/books/{other}/form").json()
    assert form["templates"] and form["player_entities"]
    sheets = sample()
    pv = visitor.post(
        f"/api/books/{other}/preview",
        json={"template": sheets[0]["template"], "sheet": sheets[0]["sheet"]},
    ).json()
    assert pv["derived"]
    fm = visitor.post(f"/api/books/{other}/formula", json={"formula": "1 +"}).json()
    assert fm["problems"]


def test_library_characters_can_be_made_changed_and_deleted_outside_games(site: Site) -> None:
    book = import_pack(site, "tests/fixtures/rulepack_single.json")
    a, b = site.client(), site.client()
    sheets = sample()
    made = a.post(
        f"/api/books/{book}/characters",
        json={"sheets": sheets, "name": "甲", "summary": "一", "password": "pw", "author": "作者"},
    ).json()
    assert made["locked"] and made["created_by"] == "作者"
    assert [c["id"] for c in b.get(f"/api/books/{book}").json()["character_list"]] == [made["id"]]
    cid = made["id"]
    # 打开、修改要密码
    r = b.post(f"/api/books/{book}/characters/{cid}/open", json={})
    assert r.json()["detail"]["code"] == "library.bad_password"
    full = b.post(f"/api/books/{book}/characters/{cid}/open", json={"password": "pw"}).json()
    assert full["sheets"] == sheets
    changed = json.loads(json.dumps(sheets))
    changed[0]["sheet"]["name"] = "改过"
    r = b.put(f"/api/books/{book}/characters/{cid}", json={"sheets": changed, "name": "乙"})
    assert r.json()["detail"]["code"] == "library.bad_password"
    up = b.put(
        f"/api/books/{book}/characters/{cid}",
        json={"sheets": changed, "name": "乙", "summary": "二", "password": "pw"},
    ).json()
    assert (up["name"], up["summary"]) == ("乙", "二")
    again = a.post(f"/api/books/{book}/characters/{cid}/open", json={"password": "pw"}).json()
    assert again["sheets"] == changed
    # 删除也要密码
    r = b.post(f"/api/books/{book}/characters/{cid}/delete", json={"password": "nope"})
    assert r.json()["detail"]["code"] == "library.bad_password"
    assert b.post(f"/api/books/{book}/characters/{cid}/delete", json={"password": "pw"}).json() == {
        "ok": True
    }
    assert b.get(f"/api/books/{book}").json()["character_list"] == []
    # 别的规则书下没有这个角色
    other = import_pack(site, "rulepacks/grail/pack.json")
    r = a.post(f"/api/books/{other}/characters/{cid}/open", json={})
    assert r.status_code == 404
