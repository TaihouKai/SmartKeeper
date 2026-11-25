"""情报：看见就知道、认出了别人用的什么、KP 给的线索。全部记进日志，只给那个玩家看。"""

from __future__ import annotations

from typing import Any

import pytest

from smartkeeper.contracts import (
    GroupPreset,
    InsightRule,
    IntelIn,
    PackParam,
    PatchOp,
    RulePack,
    UseResult,
    ValidationFailed,
)
from smartkeeper.rules import RulesService
from tests.engine.harness import Table, setup_table
from tests.engine.test_timeline import publish, wait
from tests.fixtures import load_pack


def intel_pack(when: str = "") -> RulePack:
    pack = load_pack("single")
    tpl = pack.templates[0]
    g = tpl.groups[0]
    g = g.model_copy(
        update={
            "presets": (
                *g.presets,
                GroupPreset(name="shout", fields={"level": 1}, config="noise = 100\nrange = 1000"),
            ),
            # 喊出来才暴露名字；暴露时连职业也暴露
            "reveal": "this.loud",
            "reveal_fields": ("occupation",),
        }
    )
    tpl = tpl.model_copy(update={"groups": (g, *tpl.groups[1:])})
    rule = InsightRule(name="glance", fields=("occupation", "str"), when=when)
    loud = PackParam(name="loud", choices=("no=0", "yes=1"), groups=(g.name,))
    return pack.model_copy(update={"templates": (tpl,), "insights": (rule,), "params": (loud,)})


def table(when: str = "") -> tuple[Table, str, str]:
    pack = intel_pack(when)
    assert RulesService().validate_pack(pack) == []
    t = setup_table("single", 2, pack=pack)
    a, b = (t.entities(p)[0] for p in t.players)
    return t, a, b


def known(t: Table, pid: str, about: str) -> dict[str, Any]:
    out: dict[str, Any] = {"notes": [], "entries": []}
    for f in t.engine.player_intel(t.game_id, pid).get(about, ()):
        if f.kind == "field" and f.field is not None:
            out[f.field.name] = f.field.value
        elif f.kind == "entry":
            out["entries"].append(f.entry)
        else:
            out["notes"].append(f.text)
    return out


def next_round(t: Table) -> None:
    for p in t.players:
        wait(t, p, 10)
    t.play_round()


def test_seen_at_a_glance_at_the_start_and_again_when_a_value_changes() -> None:
    t, a, b = table()
    p0, p1 = t.players
    k = known(t, p0, b)
    assert k["occupation"] and k["str"] is not None
    assert known(t, p1, a)["occupation"]
    evs = [x for x in t.engine.view_for(t.game_id, p0) if x.type == "intel_gained"]
    assert len(evs) == 1
    # 没变就不再说；变了再说一次，只说变了的
    next_round(t)
    assert len([x for x in t.engine.view_for(t.game_id, p0) if x.type == "intel_gained"]) == 1
    job = "officer" if known(t, p0, b)["occupation"] != "officer" else "doctor"
    t.engine.admin_patch(
        t.game_id, [PatchOp(op="replace", path=f"/entities/{b}/sheet/fields/occupation", value=job)]
    )
    next_round(t)
    evs = [x for x in t.engine.view_for(t.game_id, p0) if x.type == "intel_gained"]
    assert len(evs) == 2
    assert [f["field"]["name"] for f in evs[-1].payload["facts"]] == ["occupation"]  # type: ignore[index]
    assert known(t, p0, b)["occupation"] == job
    # 别的玩家看不到我的情报
    assert all(
        x.type != "intel_gained" or x.payload["player"] == p1
        for x in t.engine.view_for(t.game_id, p1)
    )


def test_condition_is_worked_out_on_the_observer_with_target_for_the_subject() -> None:
    t, _a, b = table(when="target.str >= 1000")
    assert known(t, t.players[0], b) == {"notes": [], "entries": []}


def test_a_use_reveals_its_name_and_fields_only_when_the_group_says_so() -> None:
    t, a, b = table()
    p0, p1 = t.players
    for loud in (0, 1):
        for p in t.players:
            wait(t, p, 10)
        t.engine.close_round(t.game_id)
        t.engine.begin_plan(t.game_id)
        u = t.engine.use_entry(t.game_id, a, "shout", b, {"loud": loud}, "shout")
        assert u.payload["reveal"] is bool(loud)
        publish(t, t.players, uses=[UseResult(seq=u.seq)])
        heard = [
            x.payload["entry"]
            for x in t.engine.view_for(t.game_id, p1)
            if x.type == "entry_noticed"
        ]
        assert heard[-1] == ("shout" if loud else None)
        assert ("shout" in known(t, p1, a)["entries"]) is bool(loud)
    assert known(t, p1, a)["occupation"]
    assert "shout" not in known(t, p0, b)["entries"]


def test_kp_clues_name_entities_the_way_the_reader_knows_them() -> None:
    t, _a, b = table()
    p0, _p1 = t.players
    for p in t.players:
        wait(t, p, 10)
    adj = t.simple_adjudication().model_copy(
        update={
            "intel": (IntelIn(player=p0, about=b, text="{{" + b + "}} limps; {{nobody}} was here"),)
        }
    )
    t.play_round(adj)
    note = known(t, p0, b)["notes"][0]
    label = t.engine.handles(p0)
    assert "{{" not in note and any(f"@{h.label}" in note for h in label)
    # 事件里给玩家的是代号引用，不是实体 id
    view = t.engine.intel_event_view(
        t.game_id,
        p0,
        next(
            x
            for x in t.engine.view_for(t.game_id, p0)
            if x.type == "intel_gained" and x.actor == "kp"
        ).payload,
    )
    assert view["ref"] == t.engine.ref_for_entity(p0, b)
    # 见过的人的列表里带着情报
    seen = next(s for s in t.engine.scene(t.game_id, p0).seen if s.ref == view["ref"])
    assert any(f.kind == "note" for f in seen.intel)


@pytest.mark.parametrize(
    ("item", "code"),
    [
        (IntelIn(player="nobody", about="x", text="t"), "adj.intel_unknown_player"),
        (IntelIn(player="P0", about="ghost", text="t"), "adj.intel_unknown_entity"),
        (IntelIn(player="P0", about="A", text="t"), "adj.intel_own_entity"),
        (IntelIn(player="P0", about="B"), "adj.intel_empty"),
        (IntelIn(player="P0", about="B", fields=("wings",)), "adj.intel_unknown_field"),
    ],
)
def test_bad_intel_is_rejected(item: IntelIn, code: str) -> None:
    t, a, b = table()
    names = {"P0": t.players[0], "A": a, "B": b}
    item = item.model_copy(
        update={
            "player": names.get(item.player, item.player),
            "about": names.get(item.about, item.about),
        }
    )
    for p in t.players:
        wait(t, p, 10)
    t.engine.close_round(t.game_id)
    with pytest.raises(ValidationFailed) as err:
        t.engine.apply_adjudication(
            t.game_id, t.simple_adjudication().model_copy(update={"intel": (item,)})
        )
    assert code in [p.code for p in err.value.problems]


def test_pack_validation_checks_insights_and_reveal_fields() -> None:
    pack = intel_pack()
    bad = pack.model_copy(
        update={
            "insights": (
                InsightRule(name="x", subjects=("ghost",)),
                InsightRule(name="y", fields=("wings",), groups=("nope",)),
            )
        }
    )
    codes = {p.code for p in RulesService().validate_pack(bad)}
    assert {"pack.unknown_template", "pack.unknown_field", "pack.unknown_group"} <= codes
    tpl = pack.templates[0]
    g = tpl.groups[0].model_copy(update={"reveal_fields": ("wings",), "reveal": "this.nope"})
    bad = pack.model_copy(update={"templates": (tpl.model_copy(update={"groups": (g,)}),)})
    codes = {p.code for p in RulesService().validate_pack(bad)}
    assert {"pack.unknown_field", "formula.unknown_name"} <= codes


def test_descriptions_may_cite_rulebook_sections_that_exist() -> None:
    pack = intel_pack()
    tpl = pack.templates[0]
    cited = tpl.model_copy(update={"description": "see [[Making a person]] and [[Nowhere]]"})
    bad = pack.model_copy(
        update={"templates": (cited,), "handbook": "# Rules\n\n## **Making a person**\n\ntext"}
    )
    probs = [
        p for p in RulesService().validate_pack(bad) if p.code == "pack.unknown_handbook_section"
    ]
    assert [p.params["name"] for p in probs] == ["Nowhere"]
