"""模型配置：管理员建几套，开局时选一套，KP 的调用按局走那一套。"""

from __future__ import annotations

from tests.web.conftest import Site, setup_game


def profile(name: str, judge: str, writer: str, provider: str = "fake") -> dict[str, str]:
    return {
        "id": "",
        "name": name,
        "judge_provider": provider,
        "judge_model": judge,
        "writer_provider": provider,
        "writer_model": writer,
    }


def test_each_game_uses_the_profile_it_picked(site: Site) -> None:
    a = site.admin
    listed = a.get("/api/admin/llm-profiles").json()
    assert listed["profiles"] == [] and "fake" in listed["providers"]
    assert listed["default"]["id"] == ""
    best = a.post("/api/admin/llm-profiles", json=profile("正式版", "big", "small")).json()
    assert best["id"]
    plain, _ = setup_game(site, 1)
    # 没选的局用服务器默认那套
    assert site.services.llm(plain, True)[1] == site.settings.judge_model
    gid, _ = setup_game(site, 1, settings={"llm_profile": best["id"]})
    assert site.services.llm(gid, True)[1] == "big"
    assert site.services.llm(gid, False)[1] == "small"
    # 审核角色卡是其余调用那一档：调用记录里是这套的模型
    assert {
        c.model for c in site.services.llm_log.list(gid) if c.purpose == "review_character"
    } == {"small"}
    # 局的设置里可以换回默认
    a.patch(f"/api/admin/games/{gid}", json={"settings": {"llm_profile": ""}})
    assert site.services.llm(gid, False)[1] == site.settings.writer_model
    a.patch(f"/api/admin/games/{gid}", json={"settings": {"llm_profile": best["id"]}})
    # 改了这套，下一次调用就换过去
    a.post("/api/admin/llm-profiles", json={**best, "writer_model": "tiny"})
    assert site.services.llm(gid, False)[1] == "tiny"
    # 有没结束的局在用，不能删
    r = a.delete(f"/api/admin/llm-profiles/{best['id']}")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "llm_profile.in_use"


def test_profiles_are_checked(site: Site) -> None:
    a = site.admin
    r = a.post("/api/admin/llm-profiles", json=profile("x", "m", "m", provider="nowhere"))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "llm_profile.unknown_provider"
    assert a.post("/api/admin/llm-profiles", json=profile(" ", "m", "m")).status_code == 422
    assert a.post("/api/admin/llm-profiles", json=profile("x", "m", "")).status_code == 422
    gid, _ = setup_game(site, 1)
    r = a.patch(f"/api/admin/games/{gid}", json={"settings": {"llm_profile": "nope"}})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "llm_profile.not_found"
    tmp = a.post("/api/admin/llm-profiles", json=profile("测试版", "m", "m")).json()
    assert a.delete(f"/api/admin/llm-profiles/{tmp['id']}").status_code == 200
    assert a.get("/api/admin/llm-profiles").json()["profiles"] == []
