"""建卡助手：上下文里有规则书、结构和语法手册；给出的修改按规则书检查，检查不过让模型改一次。"""

from __future__ import annotations

import json
from typing import Any

from smartkeeper.contracts import CopilotFocus, CopilotQuestion, CopilotTurn
from smartkeeper.copilot import Copilot
from smartkeeper.llm import FakeLLM
from smartkeeper.rules import RulesService
from tests.fixtures import load_pack

MESSAGES = {
    "zh": {
        "docs.cat.config": "怎么用",
        "config.c.target": "对象",
        "copilot.fix_intro": "检查出问题，改好再给一遍：",
        "copilot.need_json": "请只输出 JSON",
        "codes.formula.unknown_name": "不认识的名字 {name}",
    }
}


def make() -> tuple[Copilot, FakeLLM]:
    llm = FakeLLM()
    return Copilot(
        lambda _g: (llm, "m"), RulesService(), lambda p: f"STRUCTURE OF {p.world.name}", MESSAGES
    ), llm


def sheets() -> Any:
    pack = load_pack("single")
    s = next(x for x in pack.samples if x.template == "person")
    return [{"template": "person", "sheet": json.loads(json.dumps(s.sheet))}]


def reply(answer: str, *proposals: dict[str, Any]) -> str:
    return json.dumps({"answer": answer, "proposals": list(proposals)}, ensure_ascii=False)


def test_context_has_the_rulebook_the_reference_and_the_sheet() -> None:
    cop, llm = make()
    pack = load_pack("single")
    entry = {"name": "steady", "fields": {"level": 1}, "description": "keeps calm"}
    llm.push(
        "copilot",
        reply("加好了", {"kind": "entry", "template": "person", "group": "skills", "entry": entry}),
    )
    q = CopilotQuestion(
        question="加一个技能",
        history=(
            CopilotTurn(role="user", text="之前问过"),
            CopilotTurn(role="assistant", text="之前答过"),
        ),
        sheets=sheets(),
    )
    a = cop.ask(pack, q)
    assert a.answer == "加好了"
    assert [p.problems for p in a.proposals] == [()]
    call = llm.by_purpose("copilot")[0]
    assert f"STRUCTURE OF {pack.world.name}" in call.system
    assert "对象" in call.system  # 语法手册（翻译过的）
    assert [m["role"] for m in call.messages] == ["user", "assistant", "user"]
    assert "加一个技能" in str(call.messages[-1]["content"])


def test_proposals_that_fail_the_rules_are_sent_back_once() -> None:
    cop, llm = make()
    bad = {"name": "x", "fields": {"level": 1}, "script": "self.nope -= 1"}
    good = {"name": "x", "fields": {"level": 1}, "script": ""}
    llm.push(
        "copilot",
        reply("第一版", {"kind": "entry", "template": "person", "group": "skills", "entry": bad}),
        reply("第二版", {"kind": "entry", "template": "person", "group": "skills", "entry": good}),
    )
    a = cop.ask(load_pack("single"), CopilotQuestion(question="写一个", sheets=sheets()))
    assert a.answer == "第二版" and a.proposals[0].problems == ()
    fix = str(llm.by_purpose("copilot")[1].messages[-1]["content"])
    assert "检查出问题" in fix and "groups.skills[1].script" in fix


def test_editing_an_entry_replaces_it_and_unknown_groups_are_reported() -> None:
    cop, llm = make()
    current = sheets()
    current[0]["sheet"]["groups"] = {"skills": [{"name": "old", "fields": {"level": 1}}]}
    new = {"name": "old", "fields": {"level": 2}}
    llm.push(
        "copilot",
        reply(
            "改好了",
            {"kind": "entry", "template": "person", "group": "skills", "entry": new},
            {"kind": "entry", "template": "person", "group": "nope", "entry": new},
        ),
        reply("还是这样"),
    )
    focus = CopilotFocus(template="person", group="skills", entry={"name": "old"})
    a = cop.ask(
        load_pack("single"), CopilotQuestion(question="升一级", sheets=current, focus=focus)
    )
    assert a.proposals[0].problems == ()
    assert [p.code for p in a.proposals[1].problems] == ["copilot.unknown_group"]
    assert "正在编辑的条目" in str(llm.by_purpose("copilot")[0].messages[-1]["content"])


def test_answers_that_are_not_json_are_asked_again_then_kept_as_text() -> None:
    cop, llm = make()
    llm.push("copilot", "随便说说", "还是随便说说")
    a = cop.ask(load_pack("single"), CopilotQuestion(question="?"))
    assert a.answer == "还是随便说说" and a.proposals == ()
    assert len(llm.by_purpose("copilot")) == 2
