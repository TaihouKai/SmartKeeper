"""在引擎上实际跑几轮（不调用模型，KP 的裁定是脚本写好的）：检查规则包里的战斗、魔力、死亡、隐匿是否按规则书执行。

uv run python rulepacks/grail/playtest.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from smartkeeper.contracts import (  # noqa: E402
    ENGINE,
    ActionItem,
    Intent,
    PatchOp,
    ReactionChoice,
    UseResult,
)
from smartkeeper.rules.store import parse_import  # noqa: E402
from tests.engine.harness import Table, setup_table  # noqa: E402

PACK = parse_import((Path(__file__).with_name("pack.json")).read_text(encoding="utf-8"))
FAILED: list[str] = []


def ok(cond: bool, what: str) -> None:
    print(("  ok  " if cond else "  FAIL ") + what)
    if not cond:
        FAILED.append(what)


def state(t: Table) -> dict[str, Any]:
    return cast(dict[str, Any], t.engine.world_state(t.game_id))


def fields(t: Table, eid: str) -> dict[str, Any]:
    return state(t)["entities"][eid]["sheet"]["fields"]


def patch(t: Table, ops: list[PatchOp]) -> None:
    e = t.engine
    e._events.append(  # pyright: ignore[reportPrivateUsage]
        t.game_id,
        e.round(t.game_id).no,
        [e._patch_event(ops, cause="playtest", actor=ENGINE)],  # pyright: ignore[reportPrivateUsage]
    )


def begin(t: Table, seconds: int = 10) -> None:
    for p in t.players:
        ent = t.entities(p)[0]
        t.engine.declare_action(
            p, "wait", Intent(items=(ActionItem(actor=ent, verb="wait", act_seconds=seconds),))
        )
    t.engine.close_round(t.game_id)
    t.engine.begin_plan(t.game_id)


def publish(t: Table, seqs: list[int]) -> None:
    e = t.engine
    adj = t.simple_adjudication(uses=[UseResult(seq=s) for s in seqs])
    e.apply_adjudication(t.game_id, adj)
    for o in adj.outcomes:
        e.set_feedback_draft(t.game_id, o.player_id, "fb")
    e.publish_round(t.game_id)


def planned(t: Table, seq: int) -> dict[str, Any]:
    return next(
        cast(dict[str, Any], x)
        for x in t.engine.planned_uses(t.game_id)
        if cast(dict[str, Any], x)["seq"] == seq
    )


def who(t: Table, pid: str) -> tuple[str, str]:
    """(御主, 英灵)"""
    ents = t.entities(pid)
    m = next(x for x in ents if state(t)["entities"][x]["template"] == "master")
    s = next(x for x in ents if state(t)["entities"][x]["template"] == "servant")
    return m, s


def main() -> int:
    t = setup_table("single", 2, pack=PACK)
    e, g = t.engine, t.game_id
    p0, p1 = t.players
    m0, s0 = who(t, p0)
    m1, s1 = who(t, p1)
    print("角色：", {"p0": (m0, s0), "p1": (m1, s1)})

    print("\n1. 英灵近战，对方闪避 / 反击 / 不抵抗")
    begin(t)
    hits = [e.use_entry(g, s0, "近战攻击", s1, {}, f"第{i}刀") for i in range(3)]
    ok(all(h.payload["waiting_for"] == p1 for h in hits), "对象是玩家：等他应对")
    prompt = {x.seq: x for x in e.reaction_prompts(g, p1)}[hits[0].seq]
    ok(
        {s.entry for s in prompt.skills} == {"反击", "闪避"},
        f"能选的应对：{[s.entry for s in prompt.skills]}",
    )
    e.react(
        g,
        p1,
        [
            ReactionChoice(seq=hits[0].seq, kind="skill", entry="闪避"),
            ReactionChoice(seq=hits[1].seq, kind="skill", entry="反击"),
            ReactionChoice(seq=hits[2].seq),
        ],
    )
    for h, how in zip(hits, ("闪避", "反击", "不抵抗"), strict=True):
        p = planned(t, h.seq)
        a = p.get("check") or {}
        d = (p.get("reaction") or {}).get("check") or {}
        print(
            f"  {how}: 攻击 {a.get('roll', {}).get('total')}→{a.get('level_name')}，"
            f"应对 {d.get('roll', {}).get('total')}→{d.get('level_name')}，命中 {p['hit']}，"
            f"伤害 {[x['amount'] for x in p['actions'] if x['op'] == 'damage']}，"
            f"反击伤害 {[x['amount'] for x in (p.get('reaction') or {}).get('actions', []) if x['op'] == 'damage']}"
        )
    hp1 = fields(t, s1)["hp"]
    publish(t, [h.seq for h in hits])
    print(f"  p1 英灵生命 {hp1} → {fields(t, s1)['hp']}，p0 英灵生命 {fields(t, s0)['hp']}")
    dead = "dead" in [s["tag"] for s in state(t)["entities"][s1]["sheet"]["statuses"]]
    ok(dead == (fields(t, s1)["hp"] <= 0), f"生命值到 0 就死（死了：{dead}）")
    # 试下一项：把 p1 的英灵恢复原样
    patch(
        t,
        [
            PatchOp(op="replace", path=f"/entities/{s1}/sheet/statuses", value=[]),
            PatchOp(op="replace", path=f"/entities/{s1}/sheet/fields/hp", value=64),
        ],
    )

    print("\n2. 御主的攻击魔术打英灵：对魔力 A 减 25 点")
    begin(t)
    mp0 = fields(t, m0)["mp"]
    zap = e.use_entry(g, m0, "攻击魔术", s1, {"mp_spent": 20}, "魔弹")
    e.react(g, p1, [ReactionChoice(seq=zap.seq)])
    p = planned(t, zap.seq)
    dmg = [x for x in p["actions"] if x["op"] == "damage"]
    if p["hit"]:
        ok(
            dmg[0]["kind"] == "magic" and dmg[0]["amount"] == max(0, dmg[0]["raw"] - 25),
            f"魔力伤害 {dmg[0]['raw']} → 实际 {dmg[0]['amount']}",
        )
    else:
        print("  没打中：", p.get("check", {}).get("level_name"))
    publish(t, [zap.seq])
    ok(abs(fields(t, m0)["mp"] - (mp0 - 20)) < 0.5, f"御主魔力 {mp0} → {fields(t, m0)['mp']}")

    print("\n3. 宝具真名解放打对方御主（近距离对城：默认困难成功；只能闪避）")
    begin(t)
    mps = fields(t, s0)["mp"]
    np_ = e.use_entry(g, s0, "真名解放", m1, {}, "解放真名")
    prompt = {x.seq: x for x in e.reaction_prompts(g, p1)}.get(np_.seq)
    ok(prompt is not None and [s.entry for s in prompt.skills] == ["闪避"], "只能闪避")
    e.react(g, p1, [ReactionChoice(seq=np_.seq, kind="skill", entry="闪避")])
    p = planned(t, np_.seq)
    print(
        f"  攻击等级 {p.get('check')} 定好的等级 {np_.payload['auto_level']}，命中 {p['hit']}，伤害 {[x['amount'] for x in p['actions'] if x['op'] == 'damage']}"
    )
    ok(np_.payload["auto_level"] == 2, "近距离对城：困难成功")
    publish(t, [np_.seq])
    spent = [x for x in p["actions"] if x["op"] == "subtract" and x["field"] == "mp"]
    ok(
        spent and spent[0]["amount"] == 25,
        f"宝具消耗 25 魔力（英灵魔力 {mps} → {fields(t, s0)['mp']}）",
    )

    print("\n4. 御主死亡：对方英灵开始消散，凶手回魔力")
    m1_dead = "dead" in [s["tag"] for s in state(t)["entities"][m1]["sheet"]["statuses"]]
    if not m1_dead:
        begin(t)
        hit = e.use_entry(g, s0, "近战攻击", m1, {}, "补刀")
        e.react(g, p1, [ReactionChoice(seq=hit.seq)])
        patch(t, [PatchOp(op="replace", path=f"/entities/{m1}/sheet/fields/hp", value=1)])
        publish(t, [hit.seq])
    m1_dead = "dead" in [s["tag"] for s in state(t)["entities"][m1]["sheet"]["statuses"]]
    ok(m1_dead, "p1 御主死了")
    f1 = fields(t, s1)
    ok(
        f1["masterless"] == 1 and 60 <= f1["remaining"] <= 240,
        f"p1 英灵失去御主，剩 {f1['remaining']} 分钟（1d4 小时）",
    )
    ok(fields(t, s0)["kills"] == 1, f"p0 英灵杀人数 {fields(t, s0)['kills']}")

    print("\n5. 重新缔结契约：p0 御主和 p1 英灵签约，消散停止")
    begin(t)
    c = e.use_entry(g, m0, "缔结契约", s1, {}, "契约")
    publish(t, [c.seq])
    f1 = fields(t, s1)
    ok(
        f1["masterless"] == 0 and f1["remaining"] >= 1,
        f"契约后：失去御主 {f1['masterless']}，剩余 {f1['remaining']}",
    )

    print("\n6. 气息遮蔽：p1 英灵改成 A 级气息遮蔽的刺客，下一轮别人要掷侦查才发现")
    patch(
        t,
        [
            PatchOp(op="replace", path=f"/entities/{s1}/sheet/fields/klass", value="Assassin"),
            PatchOp(op="replace", path=f"/entities/{s1}/sheet/fields/hp", value=48),
            PatchOp(
                op="add",
                path=f"/entities/{s1}/sheet/preset_fields",
                value={
                    "klass_skill": {"气息遮蔽": {"level": 5}},
                    "noble_phantasm": {"真名解放": {"np_type": "对人"}},
                },
            ),
            PatchOp(op="add", path=f"/entities/{s1}/detected_by", value=[]),
        ],
    )
    begin(t)
    publish(t, [])
    rolls = [
        x.payload
        for x in e.view_for(g, "kp")
        if x.type == "dice_roll"
        and x.payload.get("reason") == "search"
        and x.payload.get("against") == s1
    ]
    print("  侦查：", [(r["entity"], r["total"], r["target"], r["level"]) for r in rolls[-3:]])
    near = [r for r in rolls if r["entity"] in (m0, s0)]
    ok(bool(near) and all(r["target"] == 15 for r in near), "几米外：难度 10 + 5 × 1 = 15")
    far = [r for r in rolls if r["entity"] == "npc_1"]
    ok(all(r["target"] == 35 for r in far), "约 190 米外：难度 10 + 5 × 5 = 35")
    seen = state(t)["entities"][s1].get("detected_by", [])
    space = e._space(g)  # pyright: ignore[reportPrivateUsage]
    ok(all((x in seen) == (s1 in space.perceived_by(x)) for x in (m0, s0)), f"发现了它的：{seen}")

    print("\n7. 日常耗魔：英灵每分钟扣（2 + 技能）/ 1440")
    mp_before = fields(t, s0)["mp"]
    begin(t, seconds=600)
    publish(t, [])
    print(f"  p0 英灵魔力 {mp_before} → {fields(t, s0)['mp']}（对魔力 A：每天 4）")

    print(
        "\n结果：",
        "全部通过"
        if not FAILED
        else f"{len(FAILED)} 项没通过：{json.dumps(FAILED, ensure_ascii=False)}",
    )
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
