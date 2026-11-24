"""隐匿：stealth / search、每轮开始时的侦查、发现了才在在场列表里、攻击暴露给对象、没发现攻击者不能应对。"""

from typing import Any, cast

from smartkeeper.contracts import RulePack, UseResult
from tests.engine.harness import Table, setup_table
from tests.engine.test_timeline import magic_pack, publish, wait


def stealth_pack(search: str) -> RulePack:
    pack = magic_pack()
    tpl = pack.templates[0].model_copy(
        update={
            # 离得越远越难发现；对别的模板不隐匿
            "stealth": '(90 + distance) if observer.template == "person" else 0',
            "search": search,
        }
    )
    return pack.model_copy(update={"templates": (tpl, *pack.templates[1:])})


def perceives(t: Table, observer: str, other: str) -> bool:
    space = t.engine._space(t.game_id)  # pyright: ignore[reportPrivateUsage]
    return other in space.perceived_by(observer)


def detected_by(t: Table, eid: str) -> list[str]:
    return cast(dict[str, Any], t.engine.world_state(t.game_id))["entities"][eid].get(
        "detected_by", []
    )


def test_hidden_until_found_and_attacking_reveals() -> None:
    t = setup_table("single", 2, pack=stealth_pack("1d20"))
    e, g = t.engine, t.game_id
    p0, p1 = t.players
    a, b = t.entities(p0)[0], t.entities(p1)[0]
    rolls = [
        x
        for x in e.view_for(g, "kp")
        if x.type == "dice_roll" and x.payload.get("reason") == "search"
    ]
    # 一开局就替两个人各掷了一次侦查（1d20 够不到 92），谁也没发现谁
    assert {(x.payload["entity"], x.payload["against"]) for x in rolls} == {(a, b), (b, a)}
    assert not perceives(t, b, a) and not perceives(t, a, b)
    wait(t, p0, 10)
    wait(t, p1, 10)
    e.close_round(g)
    e.begin_plan(g)
    bolt = e.use_entry(g, a, "bolt", b, {}, "偷袭")
    assert bolt.payload["unseen"] is True
    publish(t, only=t.players, uses=[UseResult(seq=bolt.seq)])
    # 攻击暴露给对象：b 发现了 a，a 还是没发现 b
    assert detected_by(t, a) == [b]
    assert perceives(t, b, a) and not perceives(t, a, b)


def test_search_that_beats_the_difficulty_finds_at_once() -> None:
    t = setup_table("single", 2, pack=stealth_pack("1000"))
    p0, p1 = t.players
    a, b = t.entities(p0)[0], t.entities(p1)[0]
    assert detected_by(t, a) == [b] and detected_by(t, b) == [a]
    assert perceives(t, a, b) and perceives(t, b, a)
