"""技能命中按等级对抗：几个检定取最好的、定好的等级、hit 条件、应对技能、豁免、NPC 自动挑应对。"""

from typing import Any, cast

from smartkeeper.contracts import (
    ENGINE,
    CheckDef,
    GroupPreset,
    PatchOp,
    ReactionChoice,
    RulePack,
)
from tests.engine.harness import Table, setup_table
from tests.engine.test_timeline import magic_pack, wait

TIERS = "level = 0 if roll <= 10 else 1 if roll <= 15 else 2 if roll <= 20 else 3"


def duel_pack() -> RulePack:
    pack = magic_pack()
    checks = (
        CheckDef(name="hi", config=f"dice = 18\n{TIERS}"),
        CheckDef(name="lo", config=f"dice = 12\n{TIERS}"),
        CheckDef(name="dodge", config=f"dice = 18\n{TIERS}"),
        CheckDef(name="resist", config="dice = 5\nsuccess = roll > 10 + difficulty"),
    )
    extra = [
        {
            "name": "combo",
            "config": 'check = best("lo", "hi")\nreactions = ["dodge"]',
            "script": "target.damage(10 if level >= 2 else 1)",
        },
        {
            "name": "swing",
            "config": 'check = "hi"\nreactions = ["evade"]\nhit = level >= 1 and level >= opp_level',
            "script": "target.damage(4 if opposed and level == opp_level else 8)",
        },
        {
            "name": "evade",
            "config": 'target = "self"\ncheck = "dodge"',
            "script": "if reacting and level > opp_level:\n    self.negate()",
        },
        {
            "name": "nova",
            "config": 'auto_level = 3\nreactions = ["evade"]\nsave = "resist"\ndifficulty = 2',
            "script": "target.damage(1 if saved else 6)",
        },
    ]
    tpl = pack.templates[0]
    g0 = tpl.groups[0]
    g0 = g0.model_copy(
        update={
            "presets": (
                *g0.presets,
                *(GroupPreset.model_validate({"fields": {"level": 1}, **p}) for p in extra),
            )
        }
    )
    return pack.model_copy(
        update={
            "checks": (*pack.checks, *checks),
            "templates": (tpl.model_copy(update={"groups": (g0, *tpl.groups[1:])}),),
        }
    )


def start(t: Table) -> None:
    for p in t.players:
        wait(t, p, 10)
    t.engine.close_round(t.game_id)
    t.engine.begin_plan(t.game_id)


def planned(t: Table) -> dict[int, dict[str, Any]]:
    return {
        cast(dict[str, Any], x)["seq"]: cast(dict[str, Any], x)
        for x in t.engine.planned_uses(t.game_id)
    }


def damage(item: dict[str, Any]) -> list[float]:
    return [a["amount"] for a in item["actions"] if a["op"] == "damage"]


def test_player_defender_levels_hit_and_save() -> None:
    t = setup_table("single", 2, pack=duel_pack())
    e, g = t.engine, t.game_id
    p0, p1 = t.players
    a, b = t.entities(p0)[0], t.entities(p1)[0]
    start(t)
    combo = e.use_entry(g, a, "combo", b, {}, "x")
    swing = e.use_entry(g, a, "swing", b, {}, "x")
    nova = e.use_entry(g, a, "nova", b, {}, "x")
    assert combo.payload["waiting_for"] == p1
    prompts = {x.seq: x for x in e.reaction_prompts(g, p1)}
    assert prompts[combo.seq].checks == ("dodge",)
    assert [s.entry for s in prompts[combo.seq].skills] == []  # 只列了检定
    assert [s.entry for s in prompts[swing.seq].skills] == ["evade"]
    assert prompts[nova.seq].checks == ()  # 定好的等级：不掷骰，检定对抗没有意义
    e.react(
        g,
        p1,
        [
            ReactionChoice(seq=combo.seq, kind="check", check="dodge"),
            ReactionChoice(seq=swing.seq, kind="skill", entry="evade"),
            ReactionChoice(seq=nova.seq),
        ],
    )
    got = planned(t)
    # combo：hi（2）和 lo（1）取 2；闪避也是 2，平手算对象赢
    assert got[combo.seq]["hit"] is False
    assert got[combo.seq]["check"]["check"] == "hi"
    # swing：平手，evade 没作废；hit 条件让平手命中，脚本减半
    assert got[swing.seq]["reaction"]["negated"] is False
    assert got[swing.seq]["hit"] is True and damage(got[swing.seq]) == [4]
    # nova：不掷骰、等级 3；豁免 5 > 12 不成立
    assert got[nova.seq]["hit"] is True and damage(got[nova.seq]) == [6]
    assert got[nova.seq]["save"]["level"] == 0


def test_npc_defender_picks_its_best_option() -> None:
    t = setup_table("single", 1, pack=duel_pack())
    e, g = t.engine, t.game_id
    a = t.entities(t.players[0])[0]
    # NPC 挪到攻击者旁边，看得见
    pos = cast(dict[str, Any], e.world_state(g))["entities"][a]["pos"]
    move = PatchOp(op="replace", path="/entities/npc_1/pos", value={**pos, "x": pos["x"] + 2})
    e._events.append(  # pyright: ignore[reportPrivateUsage]
        g,
        e.round(g).no,
        [e._patch_event([move], cause="test", actor=ENGINE)],  # pyright: ignore[reportPrivateUsage]
    )
    start(t)
    combo = e.use_entry(g, a, "combo", "npc_1", {}, "x")
    swing = e.use_entry(g, a, "swing", "npc_1", {}, "x")
    assert combo.payload["waiting_for"] is None and e.pending_reactions(g) == []
    got = planned(t)
    # combo：闪避能让它打空，选闪避
    assert got[combo.seq]["choice"]["check"] == "dodge" and got[combo.seq]["hit"] is False
    # swing：怎么都会被打中；用 evade 至少有等级（平手减半）
    assert got[swing.seq]["choice"]["entry"] == "evade"
    assert damage(got[swing.seq]) == [4]
