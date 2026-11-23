"""脚本化的假 KP：provider=fake 时装上。不调用任何模型，按 engine 的状态生成合法的输出。

用于离线演示和浏览器端到端测试，验证“全员提交 → 自动结算 → 自动发布”的整条链路。
"""

from __future__ import annotations

import json
import re
from typing import Any

from smartkeeper.engine import Engine
from smartkeeper.llm import FakeCall, FakeLLM

_REF = re.compile(r'"ref": "(h[0-9a-f]+)",\s*"(?:name|label)": "([^"]*)"')


def _section(prompt: str, title: str) -> str:
    if f"## {title}" not in prompt:
        return ""
    return prompt.split(f"## {title}", 1)[1].split("\n## ", 1)[0]


def install_scripted(llm: FakeLLM, engine: Engine) -> None:
    def gid(c: FakeCall) -> str:
        assert c.game_id is not None
        return c.game_id

    def review(c: FakeCall) -> str:
        return json.dumps({"approved": True, "comments": "OK"})

    def opening(c: FakeCall) -> str:
        g = gid(c)
        players = [p.id for p in engine.players(g) if p.active]
        ents = engine.world_state(g).get("entities")
        need = [
            k
            for k, v in (ents if isinstance(ents, dict) else {}).items()
            if isinstance(v, dict) and v.get("pos") is None
        ]
        return json.dumps(
            {
                "broadcast": "（脚本化 KP）故事开始了。",
                "messages": {p: "（脚本化 KP）这是你的开场信息。" for p in players},
                "positions": {
                    k: {"pos": {"x": 3.0 * i, "y": -5.0, "z": 0}, "inside": None}
                    for i, k in enumerate(need)
                },
            },
            ensure_ascii=False,
        )

    def name(c: FakeCall) -> str:
        desc = _section(c.prompt, "对方的外观描述")
        m = re.search(r">([^<]*)</player_text>", desc)
        text = (m.group(1) if m else "").strip() or "?"
        return json.dumps({"label": text[:10]}, ensure_ascii=False)

    def intent(c: FakeCall) -> str:
        own = _REF.findall(
            _section(c.prompt, "可指代的对象：玩家自己控制的实体（及各自的在场列表）")
        )
        seen = _REF.findall(_section(c.prompt, "可指代的对象：玩家见过的人和物（不一定在场）"))
        action = _section(c.prompt, "行动声明")
        if not own:
            return json.dumps({"items": [], "unresolved": ["?"]})
        targets = [{"ref": ref} for ref, label in seen if label and f"@{label}" in action]
        return json.dumps(
            {
                "items": [
                    {
                        "actor": own[0][0],
                        "verb": "act",
                        "targets": targets,
                        "detail": action.strip()[:200],
                        "seconds": 60,
                    }
                ]
            },
            ensure_ascii=False,
        )

    def adjudicate(c: FakeCall) -> str:
        # 每个玩家都给结果：大家每轮都重新行动，浏览器测试走最简单的路径
        g = gid(c)
        acts = engine.activities(g)
        outcomes: list[dict[str, Any]] = []
        for p in engine.players(g):
            ents = engine.controlled(g, p.id)
            if not p.active or not ents:
                continue
            resolves = [s.item for e in ents if e in acts for s in acts[e].steps]
            outcomes.append(
                {"player_id": p.id, "resolves": resolves, "result": "（脚本化 KP）你的行动完成了。"}
            )
        return json.dumps({"outcomes": outcomes}, ensure_ascii=False)

    llm.on("review_character", review)
    llm.on("opening", opening)
    llm.on("name_handle", name)
    llm.on("chat", lambda c: "（脚本化 KP）收到你的问题。这只是离线演示的回答。")
    llm.on("parse_intent", intent)
    llm.on("claim_check", lambda c: json.dumps({"verdict": "holds", "evidence": [], "note": ""}))
    llm.on("plan", lambda c: json.dumps({"checks": [], "queries": []}))
    llm.on("adjudicate", adjudicate)
    llm.on("feedback", lambda c: "（脚本化 KP）本轮你的行动完成了，时间过去了一分钟。")
    llm.on("broadcast", lambda c: "（脚本化 KP）公共消息。")
    llm.on("leak_check", lambda c: json.dumps({"leaks": []}))
    llm.on("summary", lambda c: "（脚本化 KP）摘要。")
    llm.on(
        "npc_talk",
        lambda c: json.dumps({"text": "（脚本化 NPC）嗯。", "end": False}, ensure_ascii=False),
    )
