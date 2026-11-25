"""在引擎上实际跑几轮（不调用模型，KP 的裁定是脚本写好的）：检查规则包里的战斗、神秘、宝具、令咒、
召唤、魔力、死亡、隐匿是否按设定执行。

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
    Event,
    IntelIn,
    Intent,
    PatchOp,
    ReactionChoice,
    UseResult,
    ValidationFailed,
)
from smartkeeper.rules.store import parse_import  # noqa: E402
from tests.engine.harness import Table, setup_table  # noqa: E402

PACK = parse_import((Path(__file__).with_name("pack.json")).read_text(encoding="utf-8"))
FAILED: list[str] = []
EXCALIBUR = "誓约的胜利之剑"


def ok(cond: bool, what: str) -> None:
    print(("  ok  " if cond else "  FAIL ") + what)
    if not cond:
        FAILED.append(what)


def state(t: Table) -> dict[str, Any]:
    return cast(dict[str, Any], t.engine.world_state(t.game_id))


def fields(t: Table, eid: str) -> dict[str, Any]:
    return state(t)["entities"][eid]["sheet"]["fields"]


def tags(t: Table, eid: str) -> list[str]:
    return [s["tag"] for s in state(t)["entities"][eid]["sheet"]["statuses"]]


def patch(t: Table, ops: list[PatchOp]) -> None:
    e = t.engine
    e._events.append(  # pyright: ignore[reportPrivateUsage]
        t.game_id,
        e.round(t.game_id).no,
        [e._patch_event(ops, cause="playtest", actor=ENGINE)],  # pyright: ignore[reportPrivateUsage]
    )


def place(t: Table, eid: str, x: float, y: float) -> None:
    patch(t, [PatchOp(op="replace", path=f"/entities/{eid}/pos", value={"x": x, "y": y, "z": 0})])


def begin(t: Table, seconds: int = 10) -> None:
    for p in t.players:
        ent = t.entities(p)[0]
        t.engine.declare_action(
            p, "wait", Intent(items=(ActionItem(actor=ent, verb="wait", act_seconds=seconds),))
        )
    t.engine.close_round(t.game_id)
    t.engine.begin_plan(t.game_id)


def publish(t: Table, uses: list[Event]) -> None:
    e = t.engine
    adj = t.simple_adjudication(uses=[UseResult(seq=u.seq) for u in uses])
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


def damage(p: dict[str, Any]) -> list[float]:
    return [x["amount"] for x in p["actions"] if x["op"] == "damage"]


def who(t: Table, pid: str) -> tuple[str, str]:
    """(御主, 英灵)"""
    ents = t.entities(pid)
    m = next(x for x in ents if state(t)["entities"][x]["template"] == "master")
    s = next(x for x in ents if state(t)["entities"][x]["template"] == "servant")
    return m, s


def heal(t: Table, *eids: str) -> None:
    ops: list[PatchOp] = []
    for eid in eids:
        f = fields(t, eid)
        hp_max = t.engine.derived_all(t.game_id)[eid]["hp_max"]
        ops.append(PatchOp(op="replace", path=f"/entities/{eid}/sheet/statuses", value=[]))
        if f.get("hp") is not None:
            ops.append(PatchOp(op="replace", path=f"/entities/{eid}/sheet/fields/hp", value=hp_max))
    patch(t, ops)


def noticed(t: Table, pid: str, since: int) -> list[Any]:
    return [
        x.payload.get("entry")
        for x in t.engine.view_for(t.game_id, pid, since)
        if x.type == "entry_noticed"
    ]


def known(t: Table, pid: str, about: str) -> dict[str, Any]:
    """这个玩家知道的关于 about 的事：字段名 -> 值，条目名 -> True，线索 -> 文字列表。"""
    out: dict[str, Any] = {"notes": []}
    for f in t.engine.player_intel(t.game_id, pid).get(about, ()):
        if f.kind == "field" and f.field is not None:
            out[f.field.name] = f.field.shown or f.field.value
        elif f.kind == "entry":
            out[f.entry] = True
        else:
            out["notes"].append(f.text)
    return out


def main() -> int:
    t = setup_table("single", 2, pack=PACK)
    e, g = t.engine, t.game_id
    p0, p1 = t.players
    m0, s0 = who(t, p0)
    m1, s1 = who(t, p1)
    print("角色：", {"p0": (m0, s0), "p1": (m1, s1)})
    # 两组人隔开 30 米：p0 在西，p1 在东
    for eid, x in ((m0, -80), (s0, -70), (s1, -40), (m1, -38)):
        place(t, eid, x, -40)

    print("\n1. 英灵近战，对方闪避 / 反击 / 不抵抗")
    place(t, s0, -42, -40)
    begin(t)
    hits = [e.use_entry(g, s0, "近战攻击", s1, {}, f"第{i}刀") for i in range(3)]
    prompt = {x.seq: x for x in e.reaction_prompts(g, p1)}[hits[0].seq]
    ok({s.entry for s in prompt.skills} == {"反击", "闪避"}, "能选的应对：反击、闪避")
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
        print(f"  {how}: 命中 {p['hit']}，伤害 {damage(p)}")
    publish(t, hits)
    heal(t, s0, s1)
    place(t, s0, -70, -40)
    k = known(t, p0, s1)
    ok(
        k.get("klass") == "Saber" and "str" in k and "true_name" not in k,
        f"御主的透视：p0 看见了 p1 的英灵，知道职阶和参数、不知道真名 {k}",
    )
    ok("klass" not in known(t, p0, m1), "御主看别的御主看不出参数")

    print("\n2. 神秘：普通的武器伤不到英灵；魔术会被对魔力挡掉一部分")
    place(t, m0, -42, -40)
    begin(t)
    punch = e.use_entry(g, m0, "近战攻击", s1, {}, "一拳")
    e.react(g, p1, [ReactionChoice(seq=punch.seq)])
    p = planned(t, punch.seq)
    ok(not p["hit"] or damage(p) == [0], f"御主的拳头打英灵：命中 {p['hit']}，伤害 {damage(p)}")
    zap = e.use_entry(g, m0, "攻击魔术", s1, {"mp_spent": 20}, "魔弹")
    e.react(g, p1, [ReactionChoice(seq=zap.seq)])
    p = planned(t, zap.seq)
    dmg = [x for x in p["actions"] if x["op"] == "damage"]
    if p["hit"]:
        ok(
            dmg[0]["kind"] == "magic" and dmg[0]["amount"] == max(0, dmg[0]["raw"] - 25),
            f"魔术伤害 {dmg[0]['raw']} → 对魔力 A 挡掉 25 → {dmg[0]['amount']}",
        )
    publish(t, [punch, zap])
    heal(t, s1)
    place(t, m0, -80, -40)

    print("\n3. 宝具：平时当武器用不暴露名字；不解放真名用不了光炮；解放真名时附近的人听到名字")
    place(t, s0, -42, -40)
    begin(t)
    seq0 = max(x.seq for x in e.view_for(g, "kp"))
    swing = e.use_entry(g, s0, f"{EXCALIBUR}/当作武器", s1, {}, "挥剑")
    e.react(g, p1, [ReactionChoice(seq=swing.seq)])
    try:
        e.use_entry(g, s0, f"{EXCALIBUR}/真名解放·对城", m1, {}, "不解放就放")
        ok(False, "不解放真名不该能用光炮")
    except ValidationFailed as err:
        ok(err.code == "use.requires", "不解放真名：光炮用不了（use.requires）")
    publish(t, [swing])
    heard = noticed(t, p1, seq0)
    ok(heard and all(x is None for x in heard), f"挥剑：p1 只察觉到有人用了点什么 {heard}")
    ok(EXCALIBUR not in known(t, p1, s0), "挥剑：p1 的情报里没有宝具的名字")
    asked = [x for x in e.view_for(g, p1, seq0) if x.type == "reaction_requested"]
    ok(
        bool(asked) and all(x.payload.get("entry") == "" for x in asked),
        "被砍的人也不知道砍他的是什么",
    )
    heal(t, s1)
    place(t, s0, -70, -40)

    begin(t)
    seq0 = max(x.seq for x in e.view_for(g, "kp"))
    mp0 = fields(t, s0)["mp"]
    beam = e.use_entry(g, s0, f"{EXCALIBUR}/真名解放·对城", m1, {"release": 1}, "解放")
    hit_list = [beam.payload["target"]] + [
        x["target"] for x in e.planned_uses(g) if cast(dict[str, Any], x)["area_of"] == beam.seq
    ]
    ok(set(hit_list) >= {m1, s1}, f"对城的范围扫到了 p1 的御主和英灵：{hit_list}")
    ok(beam.payload["auto_level"] == 2, "30 米内的对城：默认困难成功")
    ok(m0 not in hit_list, "身后的自己人不会被扫到")
    for pid in t.players:
        prompt = {x.seq: x for x in e.reaction_prompts(g, pid)}
        ok(all([s.entry for s in prompt[k].skills] == ["闪避"] for k in prompt), "只能闪避")
        if prompt:
            e.react(g, pid, [ReactionChoice(seq=k, kind="skill", entry="闪避") for k in prompt])
    spent = [x["amount"] for x in planned(t, beam.seq)["actions"] if x["op"] == "subtract"]
    publish(t, [beam])
    kill = 5 if "dead" in tags(t, m1) else 0  # 杀了人回 5 点
    ok(
        spent == [25] and abs(fields(t, s0)["mp"] - (mp0 - 25 + kill)) < 0.5,
        f"消耗 A 级 × 对城 = 25 魔力，杀人回 {kill}（{mp0} → {fields(t, s0)['mp']}）",
    )
    heard = noticed(t, p1, seq0)
    ok(f"{EXCALIBUR}/真名解放·对城" in heard, f"p1 听到了宝具的名字：{heard}")
    k = known(t, p1, s0)
    ok(
        k.get(EXCALIBUR) is True and k.get("true_name") == "（示例）亚瑟王",
        f"解放真名：p1 的情报里有了宝具的名字和英灵的真名 {k}",
    )
    m1_dead = "dead" in tags(t, m1)
    print(f"  p1 御主 {'死了' if m1_dead else '活着'}，生命 {fields(t, m1)['hp']}")

    print("\n4. 开关型宝具：风王结界开着时筋力高一级")
    begin(t)
    before = e.derived_all(g)[s0].get("str")
    w = e.use_entry(g, s0, "风王结界/开关", None, {}, "开风王结界")
    publish(t, [w])
    view = next(v for v in e.sheets(g, p0) if v.entity_id == s0)
    strength = next((d for d in view.derived if d.name == "str"), None)
    ok(
        strength is not None and strength.value == strength.base + 1,
        f"筋力 {strength.base if strength else '?'} → {strength.value if strength else '?'}（之前 {before}）",
    )

    print("\n5. 令咒：空间转移、魔力灌注")
    place(t, s0, 150, 150)
    patch(t, [PatchOp(op="replace", path=f"/entities/{s0}/sheet/fields/mp", value=1)])
    begin(t)
    c1 = e.use_entry(g, m0, "令咒/空间转移", None, {}, "过来")
    c2 = e.use_entry(g, m0, "令咒/魔力灌注", None, {}, "拿去")
    publish(t, [c1, c2])
    s = state(t)["entities"]
    ok(s[s0]["pos"] == s[m0]["pos"], "英灵瞬间回到御主身边")
    ok(fields(t, s0)["mp"] >= 59, f"英灵魔力补满：{fields(t, s0)['mp']}")
    ok(fields(t, m0)["command_spells"] == 1, f"令咒剩 {fields(t, m0)['command_spells']} 划")

    print("\n6. 御主死亡：对方英灵开始消散；有令咒的御主可以和它重新缔结契约")
    if "dead" not in tags(t, m1):
        patch(t, [PatchOp(op="replace", path=f"/entities/{m1}/sheet/fields/hp", value=1)])
        place(t, s0, -40, -40)
        begin(t)
        hit = e.use_entry(g, s0, "近战攻击", m1, {}, "补刀")
        e.react(g, p1, [ReactionChoice(seq=hit.seq)])
        publish(t, [hit])
    ok("dead" in tags(t, m1), "p1 御主死了")
    f1 = fields(t, s1)
    ok(
        f1["masterless"] is True and 0 < f1["remaining"] <= 240,
        f"p1 英灵失去御主，剩 {f1['remaining']} 分钟（1d4 小时）",
    )
    place(t, m0, -40, -40)
    begin(t)
    c = e.use_entry(g, m0, "缔结契约", s1, {}, "契约")
    publish(t, [c])
    ok(fields(t, s1)["masterless"] is False, "契约后停止消散")

    print("\n7. 使魔：放出 3 只，归同一个玩家控制")
    begin(t)
    fam = e.use_entry(g, m0, "使魔", None, {"mp_spent": 3}, "放使魔")
    publish(t, [fam])
    mine = [
        x for x in state(t)["controls"][p0] if state(t)["entities"][x]["template"] == "familiar"
    ]
    ok(len(mine) == 3, f"p0 控制的使魔：{mine}")

    print("\n8. 属性的“+”：筋力 ++ 发动成功后 10 分钟内 ×2（最高 9）")
    patch(t, [PatchOp(op="add", path=f"/entities/{s0}/sheet/fields/str_plus", value=2)])
    begin(t)
    up = e.use_entry(g, s0, "发动＋：筋力", None, {}, "爆发")
    publish(t, [up])
    lv = cast(dict[str, Any], up.payload.get("check") or {}).get("level_name")
    view = next(v for v in e.sheets(g, p0) if v.entity_id == s0)
    strength = next((d for d in view.derived if d.name == "str"), None)
    print(
        f"  幸运检定：{lv}；筋力 {strength.base if strength else '?'} → {strength.value if strength else '?'}"
    )
    ok(
        up.payload["hit"] is False or (strength is not None and strength.value == 9),
        "成功时筋力 A(5)+风王结界 → 翻倍封顶 9",
    )

    print("\n9. 刺客的气息遮蔽：下一轮别人要掷侦查才发现")
    patch(
        t,
        [
            PatchOp(op="replace", path=f"/entities/{s1}/sheet/fields/klass", value="Assassin"),
            PatchOp(
                op="add",
                path=f"/entities/{s1}/sheet/preset_fields",
                value={"klass_skill": {"气息遮蔽": {"level": 5}}},
            ),
            PatchOp(op="add", path=f"/entities/{s1}/detected_by", value=[]),
        ],
    )
    place(t, s1, -45, -40)
    begin(t)
    publish(t, [])
    rolls = [
        x.payload
        for x in e.view_for(g, "kp")
        if x.type == "dice_roll"
        and x.payload.get("reason") == "search"
        and x.payload.get("against") == s1
    ]
    near = [r for r in rolls if r["entity"] in (m0, s0)]
    ok(
        bool(near) and all(r["target"] == 15 for r in near),
        f"几米外：难度 10 + 5 × 1 = 15（{len(near)} 次侦查）",
    )

    print("\n10. 日常耗魔：英灵每分钟扣（2 + 技能 + 开着的宝具）/ 1440")
    mp_before = fields(t, s0)["mp"]
    begin(t, seconds=600)
    publish(t, [])
    print(
        f"  p0 英灵魔力 {mp_before} → {fields(t, s0)['mp']}（对魔力 A + 风王结界开着：每天 2 + 2 + 1 = 5）"
    )

    print("\n11. 情报：KP 判定的线索；没见过的人不能给")
    begin(t)
    adj = t.simple_adjudication().model_copy(
        update={
            "intel": (
                IntelIn(player=p0, about=s1, text="{{" + s1 + "}} 的剑路是西洋骑士的打法"),
                IntelIn(player=p0, about=s1, fields=("true_name",)),
            )
        }
    )
    e.apply_adjudication(g, adj)
    for o in adj.outcomes:
        e.set_feedback_draft(g, o.player_id, "fb")
    e.publish_round(g)
    k = known(t, p0, s1)
    ok(
        bool(k["notes"]) and "西洋骑士" in k["notes"][0] and "{{" not in k["notes"][0],
        f"p0 得到了线索（实体换成了他的叫法）：{k['notes']}",
    )
    ok("true_name" in k, f"KP 判定证据确凿时给出字段：{k.get('true_name')}")
    stranger = "npc_nobody"
    patch(
        t,
        [
            PatchOp(
                op="add",
                path=f"/entities/{stranger}",
                value={**state(t)["entities"][m1], "pos": {"x": 900, "y": 900, "z": 0}},
            )
        ],
    )
    begin(t)
    bad = t.simple_adjudication().model_copy(
        update={"intel": (IntelIn(player=p0, about=stranger, text="他是坏人"),)}
    )
    try:
        e.apply_adjudication(g, bad)
        ok(False, "没见过的人不该能给情报")
    except ValidationFailed as err:
        ok(
            any(p.code == "adj.intel_not_met" for p in err.problems),
            "没见过的人：裁定被拒（adj.intel_not_met）",
        )

    print(
        "\n结果：",
        "全部通过"
        if not FAILED
        else f"{len(FAILED)} 项没通过：{json.dumps(FAILED, ensure_ascii=False)}",
    )
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
