from __future__ import annotations

import json

import sqlalchemy as sa

from smartkeeper.contracts import KP, LLMResult, SearchRecord
from smartkeeper.kp import KPConfig
from smartkeeper.llm import FakeCall, FakeLLM, RecordingLLM, SqlLLMCallLog
from tests.kp.harness import new_game


def feedback_count(g, pid: str) -> int:  # type: ignore[no-untyped-def]
    return len([x for x in g.engine.view_for(g.game_id, pid) if x.type == "feedback"])


def test_raw_entity_id_in_feedback_is_rewritten() -> None:
    g = new_game(2)
    replies = iter(["你看见了 npc_thief。", "你看见了一个人。", "你看见了一个人。"])
    g.llm.on("feedback", lambda c: next(replies))
    g.play_round()
    assert g.engine.round(g.game_id, 1).status == "published"
    for p in g.players:
        texts = [x.payload["text"] for x in g.engine.view_for(g.game_id, p) if x.type == "feedback"]
        assert all("npc_" not in str(t) for t in texts)


def test_persistent_leak_stops_in_review_with_sentences() -> None:
    g = new_game(2)
    target = g.players[0]

    def leak(call: FakeCall) -> str:
        # 只把第一个玩家的反馈判为泄密
        own = "你的开场信息 " + target
        if own in call.prompt:
            return json.dumps(
                {"leaks": [{"sentence": "你的反馈。", "reason": "说出了真相"}]}, ensure_ascii=False
            )
        return '{"leaks": []}'

    hooks: list[tuple[str, int]] = []
    g.kp._on_review = lambda gid, n: hooks.append((gid, n))  # type: ignore[attr-defined]
    g.llm.on("leak_check", leak)
    g.play_round()
    r = g.engine.round(g.game_id, 1)
    assert r.status == "review"
    assert r.draft is not None
    leaks = r.draft["leaks"]
    assert isinstance(leaks, dict) and list(leaks) == [target]
    assert (
        len([c for c in g.llm.by_purpose("feedback") if target in c.prompt]) == 2
    )  # 自动重写了一次
    assert hooks == [(g.game_id, 1)]
    assert feedback_count(g, target) == 0


def test_rolling_summary_recorded_and_used_as_atmosphere_only() -> None:
    g = new_game(2)
    g.llm.on("summary", lambda c: "SUMMARY_MARK 局势紧张")
    published: list[int] = []
    g.kp._on_published = lambda gid, n: published.append(n)  # type: ignore[attr-defined]
    g.play_round()
    g.play_round()
    summaries = [x for x in g.engine.view_for(g.game_id, KP) if x.type == "summary"]
    assert len(summaries) == 2 and all(x.visibility.kind == "kp_only" for x in summaries)
    prompt = g.llm.by_purpose("adjudicate")[-1].prompt
    assert "## 滚动摘要（只提供氛围，不能作为事实依据）\n\nSUMMARY_MARK" in prompt
    # 摘要不会出现在玩家的视图里
    for p in g.players:
        assert all(x.type != "summary" for x in g.engine.view_for(g.game_id, p))
    assert published == [1, 2]


# ---------------- 世界观设定查询 ----------------


def searchable_llm() -> FakeLLM:
    llm = FakeLLM()
    llm.supports_search = True
    return llm


def test_web_search_off_means_no_search_tool() -> None:
    g = new_game(2, llm=searchable_llm())
    g.engine.update_settings(
        g.game_id, g.engine.game(g.game_id).settings.model_copy(update={"web_search": False})
    )
    g.play_round()
    assert not any(c.allow_search for c in g.llm.calls if c.purpose in ("plan", "adjudicate"))


def test_web_search_on_for_the_listed_calls_only() -> None:
    g = new_game(2, llm=searchable_llm())
    g.play_round()
    by = {c.purpose: c.allow_search for c in g.llm.calls}
    assert by["opening"] and by["plan"] and by["adjudicate"] and by["review_character"]
    assert not by["feedback"] and not by["parse_intent"] and not by["name_handle"]


def test_reference_sites_in_prompt_only_when_present() -> None:
    from smartkeeper.contracts import GameConfig
    from tests.engine.harness import SCENARIO_PUBLIC, make_engine
    from tests.fixtures import load_pack

    for pack_name, expect in (("multi", True), ("single", False)):
        engine, packs = make_engine()
        pack = load_pack(pack_name)
        pid = packs.create_pack("x")
        packs.save_version(pid, pack)
        g = engine.create_game(
            GameConfig(
                name="t", rulepack_id=pid, rulepack_version=1, scenario_public=SCENARIO_PUBLIC
            )
        )
        from smartkeeper.kp import Contexts

        ctx = Contexts(engine, KPConfig())
        system = ctx._system(g.id, "adjudicate")  # type: ignore[attr-defined]
        assert ("https://example.org/fixture-wiki" in system) == expect
        assert ("优先查下面这些参考网站" in system) == expect


def test_searches_are_recorded_in_llm_call() -> None:
    class Searching:
        supports_search = True
        provider = "stub"

        def complete(self, **kw: object) -> LLMResult:
            assert kw["allow_search"] is True
            return LLMResult(
                text="ok", model="m", searches=(SearchRecord(query="q", urls=("https://a",)),)
            )

    log = SqlLLMCallLog(sa.create_engine("sqlite://"))
    rec = RecordingLLM(Searching(), log)  # type: ignore[arg-type]
    rec.complete(
        purpose="adjudicate", model="m", system="s", messages=[], allow_search=True, game_id="g"
    )
    (row,) = log.list("g")
    assert row.searches[0].query == "q" and row.searches[0].urls == ("https://a",)


def test_repair_known_aliases_only() -> None:
    from smartkeeper.kp.schemas import repair_adjudication

    raw = {
        "movements": [{"entity": "ent_1", "pos": {"x": 1, "y": 2, "z": 0}, "because": "a"}],
        "encounters": [{"entities": ["ent_1", "ent_2"], "observed_by": {"ent_1": "x", "p2": "y"}}],
        "outcomes": [],
    }
    out = repair_adjudication(raw, {"ent_1": "p1", "ent_2": "p2"})
    assert out["movements"][0]["to"] == {"x": 1, "y": 2, "z": 0}  # type: ignore[index]
    assert out["encounters"][0]["players"] == ["p1", "p2"]  # type: ignore[index]
    assert out["encounters"][0]["observed_by"] == {"p1": "x", "p2": "y"}  # type: ignore[index]


def test_plan_ignores_extra_query_keys() -> None:
    from smartkeeper.kp.schemas import PlanOut, parse

    plan = parse(
        PlanOut,
        '{"checks": [], "queries": [{"query_id": "q1", "kind": "distance", "reason": "why"}]}',
    )
    assert plan.queries[0].query_id == "q1"
