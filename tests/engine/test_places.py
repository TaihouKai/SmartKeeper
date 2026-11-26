"""起了名字的地点：剧本、开场、裁定里起名字；一个名字只指一个地方；KP 文字里的 {{place:名字}} 变成链接。"""

from __future__ import annotations

from typing import Any, cast

import pytest

from smartkeeper.contracts import Place, PlaceNameIn, ValidationFailed
from tests.engine.harness import Table, setup_table


def names(t: Table) -> dict[str, dict[str, Any]]:
    raw = cast(dict[str, Any], t.engine.world_state(t.game_id))["places"]
    return {v["name"]: v for v in raw.values()}


def texts(t: Table, pid: str, kind: str) -> list[str]:
    return [str(e.payload["text"]) for e in t.engine.view_for(t.game_id, pid) if e.type == kind]


def name_place(name: str, public: bool = False, **at: Any) -> PlaceNameIn:
    return PlaceNameIn(name=name, at=Place.model_validate(at), public=public)


def test_scenario_places_are_registered_at_the_start_and_linked_in_the_opening() -> None:
    t = setup_table(
        "single",
        1,
        kp_extra="places:\n  - {name: 面包店, at: {place: Low House}}\n",
        broadcast="去{{place:面包店}}集合，钟在{{place:Clock}}，{{place:没有这个地方}}也行。",
    )
    shop = names(t)["面包店"]
    assert shop["feature"] == "bldg_low" and shop["inside"] == "bldg_low"
    (pid,) = t.players
    (text,) = texts(t, pid, "broadcast")
    assert (
        text == "去[面包店](place:place_1)集合，钟在[Clock](feature:lm_clock)，没有这个地方也行。"
    )


def test_a_round_can_name_a_place_and_its_feedback_links_to_it() -> None:
    t = setup_table("single", 1)
    (pid,) = t.players
    e, g = t.engine, t.game_id
    t.declare_all()
    e.close_round(g, forced=True)
    adj = t.simple_adjudication(places=[name_place("集合点", place="Green Park")])
    e.apply_adjudication(g, adj)
    assert "集合点" not in names(t)  # 发布之前不写入
    e.set_feedback_draft(g, pid, "你约好在{{place:集合点}}见面。")
    e.publish_round(g)
    assert names(t)["集合点"]["feature"] == "park_green"
    assert texts(t, pid, "feedback")[-1] == "你约好在[集合点](place:place_1)见面。"
    # 起过的名字在开场、NPC 的位置等地方也能当地名用
    assert (
        e.resolve_place(g, Place(place="集合点")).pos
        == e.resolve_place(g, Place(place="Green Park")).pos
    )


def round_with(t: Table, *decls: PlaceNameIn) -> None:
    e, g = t.engine, t.game_id
    t.declare_all()
    e.close_round(g, forced=True)
    e.apply_adjudication(g, t.simple_adjudication(places=list(decls)))
    for pid in t.players:
        e.set_feedback_draft(g, pid, "fb")
    e.publish_round(g)


def test_one_name_means_one_place() -> None:
    t = setup_table("single", 1)
    round_with(t, name_place("钟楼", place="Tower"))
    # 同名同地：没问题，也不会多一条
    round_with(t, name_place("钟楼", place="Tower"))
    assert len(names(t)) == 1
    # 同名不同地：整份裁定不通过
    t.declare_all()
    t.engine.close_round(t.game_id, forced=True)
    with pytest.raises(ValidationFailed) as err:
        t.engine.apply_adjudication(
            t.game_id, t.simple_adjudication(places=[name_place("钟楼", place="Low House")])
        )
    assert [p.code for p in err.value.problems] == ["place.name_taken"]
    assert err.value.problems[0].params["where"] == "Tower"


def test_a_batch_cannot_give_one_name_two_places() -> None:
    t = setup_table("single", 1)
    t.declare_all()
    t.engine.close_round(t.game_id, forced=True)
    with pytest.raises(ValidationFailed) as err:
        t.engine.apply_adjudication(
            t.game_id,
            t.simple_adjudication(
                places=[name_place("据点", place="Tower"), name_place("据点", place="Clock")]
            ),
        )
    assert [p.code for p in err.value.problems] == ["place.name_taken"]


def test_a_name_cannot_be_another_features_name_or_off_the_map() -> None:
    t = setup_table("single", 1)
    t.declare_all()
    t.engine.close_round(t.game_id, forced=True)
    with pytest.raises(ValidationFailed) as err:
        t.engine.apply_adjudication(
            t.game_id,
            t.simple_adjudication(
                places=[
                    name_place("Tower", place="Low House"),
                    name_place("远方", pos={"x": 5000, "y": 0, "z": 0}),
                ]
            ),
        )
    assert [p.code for p in err.value.problems] == [
        "place.name_is_other_feature",
        "space.out_of_bounds",
    ]


def test_a_named_building_resolves_floors_and_the_roof() -> None:
    t = setup_table("single", 1)
    round_with(t, name_place("钟楼", place="Tower"))
    third = t.engine.resolve_place(t.game_id, Place(place="钟楼", floor=3))
    roof = t.engine.resolve_place(t.game_id, Place(place="钟楼", roof=True))
    assert third.inside == "bldg_tower" and third.pos.z == 6
    assert roof.pos.z == 30


def test_who_knows_a_secret_name_follows_the_messages_they_read() -> None:
    t = setup_table("single", 2)
    p0, p1 = t.players
    e, g = t.engine, t.game_id
    t.declare_all()
    e.close_round(g, forced=True)
    e.apply_adjudication(
        g,
        t.simple_adjudication(
            places=[
                name_place("工房", place="Tower"),
                name_place("广场", place="Green Park", public=True),
            ]
        ),
    )
    e.set_feedback_draft(g, p0, "你查到了{{place:工房}}。")
    e.set_feedback_draft(g, p1, "什么都没发生。")
    e.publish_round(g)
    # 名字和地点的对应对谁都一样；知不知道这个名字各人不同
    assert {p.name for p in e.places(g).values()} == {"工房", "广场"}
    assert {p.name for p in e.known_places(g, p0).values()} == {"工房", "广场"}
    assert {p.name for p in e.known_places(g, p1).values()} == {"广场"}
    # 后来告诉了 p1（聊天回复里提到）
    e.post_kp_chat(p1, "{{place:工房}}在那栋楼里。", from_kp=True)
    assert {p.name for p in e.known_places(g, p1).values()} == {"工房", "广场"}


def test_a_secret_name_can_later_become_public() -> None:
    t = setup_table("single", 1)
    round_with(t, name_place("工房", place="Tower"))
    assert not names(t)["工房"].get("public")
    round_with(t, name_place("工房", place="Tower", public=True))
    assert names(t)["工房"]["public"] is True and len(names(t)) == 1
