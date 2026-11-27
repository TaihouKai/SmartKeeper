"""脚本化的假 KP：provider=fake 时装上。不调用任何模型，按 engine 的状态生成合法的输出。

用于离线演示和浏览器端到端测试，验证“全员提交 → 自动结算 → 自动发布”的整条链路。
"""

from __future__ import annotations

import json
import re
from typing import Any, cast

from smartkeeper.contracts import Intent
from smartkeeper.engine import Engine
from smartkeeper.llm import FakeCall, FakeLLM

_REF = re.compile(r'"ref":\s*"(h[0-9a-f]+)",\s*"(?:name|label)":\s*"([^"]*)"')


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
        # 写了“使用「技能名」”：找到有这个技能的角色，填上 entry
        actor: str = own[0][0]
        entry: str | None = None
        try:
            raw: object = json.loads(
                _section(c.prompt, "可指代的对象：玩家自己控制的实体（及各自的在场列表）")
            )
        except ValueError:
            raw = []
        mine = cast(list[dict[str, Any]], raw) if isinstance(raw, list) else []
        for name in re.findall(r"「([^」]+)」", action):
            for ent in mine:
                skills = cast(list[dict[str, Any]], ent.get("skills") or [])
                if any(x.get("name") == name for x in skills):
                    actor, entry = str(ent["ref"]), name
                    break
            if entry:
                break
        # 文本里点了地图上的位置或地物：当作目的地
        destination: dict[str, Any] | None = None
        pm = re.search(r"\]\(point:([-0-9.]+),([-0-9.]+),([-0-9.]+)\)", action)
        fm = re.search(r"\]\(feature:([A-Za-z0-9_.-]+)\)", action)
        if pm:
            x, y, z = (float(v) for v in pm.groups())
            destination = {"point": {"x": x, "y": y, "z": z}}
        elif fm and not entry:
            destination = {"feature": fm.group(1), "z": None}
        return json.dumps(
            {
                "items": [
                    {
                        "actor": actor,
                        "destination": destination,
                        "verb": "act",
                        "targets": targets,
                        "detail": action.strip()[:200],
                        "seconds": 5 if entry else 60,
                        "entry": entry,
                    }
                ]
            },
            ensure_ascii=False,
        )

    def plan(c: FakeCall) -> str:
        # 用了技能的行动条目：照着用（对象是第一个被 @ 的人）
        g = gid(c)
        uses: list[dict[str, Any]] = []
        for ev in engine.declarations(g).values():
            for it in Intent.model_validate(ev.payload["intent"]).items:
                if it.entry:
                    target = next((x.id for x in it.targets if x.kind == "entity"), None)
                    uses.append({"source": it.actor, "entry": it.entry, "target": target})
        return json.dumps({"checks": [], "queries": [], "uses": uses}, ensure_ascii=False)

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
        # 本轮用的技能都算生效（范围技能只写第一条）
        uses = [
            {"seq": u["seq"], "hit": True}
            for u in engine.planned_uses(g)
            if isinstance(u, dict) and u.get("area_of") is None
        ]
        return json.dumps({"outcomes": outcomes, "uses": uses}, ensure_ascii=False)

    def copilot(c: FakeCall) -> str:
        """离线演示的建卡助手：复述问题；正在编辑某一条时，给一个把说明改掉的修改。"""
        last = str(c.messages[-1].get("content", "")) if c.messages else ""
        question = last.split("## 问题", 1)[-1].strip()
        proposals: list[dict[str, Any]] = []
        if "正在编辑的条目：" in last:
            raw = last.split("正在编辑的条目：", 1)[1].split("\n## ", 1)[0].strip()
            try:
                loaded: object = json.loads(raw)
            except ValueError:
                loaded = None
            entry = cast(dict[str, Any], loaded) if isinstance(loaded, dict) else None
            where = (
                last.split("## 玩家正在看", 1)[1].split("\n", 2)[1]
                if "## 玩家正在看" in last
                else ""
            )
            bits = [x.strip() for x in where.split("/")]
            if entry is not None and len(bits) >= 2:
                entry = {
                    **entry,
                    "description": f"{entry.get('description', '')}（助手：{question}）",
                }
                proposals.append(
                    {
                        "kind": "entry",
                        "template": bits[0],
                        "group": bits[-1],
                        "entry": entry,
                        "note": "改了说明",
                    }
                )
        return json.dumps(
            {"answer": f"（离线演示的建卡助手）收到：{question}", "proposals": proposals},
            ensure_ascii=False,
        )

    llm.on("copilot", copilot)
    llm.on("review_character", review)
    llm.on("opening", opening)
    llm.on("name_handle", name)
    llm.on("chat", lambda c: "（脚本化 KP）收到你的问题。这只是离线演示的回答。")
    llm.on("parse_intent", intent)
    llm.on("claim_check", lambda c: json.dumps({"verdict": "holds", "evidence": [], "note": ""}))
    llm.on("plan", plan)
    llm.on(
        "instant",
        lambda c: json.dumps(
            {"result": "（脚本化 KP）你做完了。", "state_patch": []}, ensure_ascii=False
        ),
    )
    llm.on("adjudicate", adjudicate)
    llm.on("feedback", lambda c: "（脚本化 KP）本轮你的行动完成了，时间过去了一分钟。")
    llm.on("broadcast", lambda c: "（脚本化 KP）公共消息。")
    llm.on("leak_check", lambda c: json.dumps({"leaks": []}))
    llm.on("summary", lambda c: "（脚本化 KP）摘要。")
    llm.on(
        "npc_talk",
        lambda c: json.dumps({"text": "（脚本化 NPC）嗯。", "end": False}, ensure_ascii=False),
    )
