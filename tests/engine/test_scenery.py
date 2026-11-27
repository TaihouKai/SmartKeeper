from __future__ import annotations

from smartkeeper.contracts import ActionItem, Intent, Location, Point
from tests.engine.harness import setup_table

# 夹具规则包 single：2 米/秒；开局在 (-50, -40) 和 (-48, -40)。小地图上 Main Street 在 y=-10，Tower 是 (0,0)-(20,20)


def test_scenery_lists_named_places_along_the_way_and_the_clock() -> None:
    t = setup_table("single", 2)
    e, g = t.engine, t.game_id
    walker, idler = t.players
    ent = t.entities(walker)[0]
    go = ActionItem(actor=ent, verb="go", destination=Location(pos=Point(x=10, y=-5, z=0)))
    e.declare_action(walker, "go", Intent(items=(go,)))
    t.declare_all([idler])
    e.close_round(g)
    lines = e.scenery(g, walker)
    assert lines[0].startswith("本轮结束时：第 1 天")
    passed = next(x for x in lines if "沿途经过" in x)
    assert "Main Street" in passed
    end = next(x for x in lines if "本轮结束时在" in x)
    assert "在户外" in end and "Tower" in end
    # 原地没动的：没有“沿途经过”
    assert not any("沿途经过" in x for x in e.scenery(g, idler))


def test_feedback_facts_are_published_next_to_the_prose() -> None:
    t = setup_table("single", 2)
    e, g = t.engine, t.game_id
    t.declare_all()
    e.close_round(g)
    adj = t.simple_adjudication()
    e.apply_adjudication(g, adj)
    for o in adj.outcomes:
        e.set_feedback_draft(
            g, o.player_id, "霓虹映在路面上。nothing happens", "结果：nothing happens"
        )
    e.publish_round(g)
    fb = [x for x in e.view_for(g, t.players[0]) if x.type == "feedback"][-1]
    assert fb.payload["facts"] == "结果：nothing happens"
    assert "霓虹" in str(fb.payload["text"])
