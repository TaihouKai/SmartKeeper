"""world 的单独测试：用假的 Rules，不加载 rules 的真实实现。"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import JsonValue

from smartkeeper.contracts import (
    EntityTemplate,
    PatchOp,
    PlayerEntities,
    Problem,
    RulePack,
    State,
    ValidationFailed,
    WorldInfo,
)
from smartkeeper.world import WorldService, apply_patch


class FakeRules:
    """只认一个模板 t：fields.hp 必须是 0..10 的数。"""

    def validate_sheet(self, pack: RulePack, template: str, sheet: JsonValue) -> list[Problem]:
        assert isinstance(sheet, dict)
        fields = sheet.get("fields")
        assert isinstance(fields, dict)
        hp = fields.get("hp")
        if not isinstance(hp, int) or not 0 <= hp <= 10:
            return [Problem(code="sheet.above_max", path="fields.hp")]
        return []

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"unexpected call {name}")


PACK = RulePack(
    world=WorldInfo(name="w"),
    templates=(EntityTemplate(name="t"),),
    player_entities=(PlayerEntities(template="t"),),
)


@pytest.fixture
def world() -> WorldService:
    return WorldService(FakeRules())  # type: ignore[arg-type]


def with_entity(world: WorldService) -> State:
    s = world.initial_state("m1")
    return world.apply(
        s,
        [
            PatchOp(
                op="add",
                path="/entities/e1",
                value={
                    "template": "t",
                    "pos": {"x": 0, "y": 0, "z": 0},
                    "inside": None,
                    "sheet": {"name": "A", "fields": {"hp": 5}, "statuses": []},
                },
            ),
            PatchOp(op="add", path="/controls/p1", value=["e1"]),
        ],
    )


def test_rfc6902_basics() -> None:
    doc: JsonValue = {"a": [1, 2], "b": {"c": 1}}
    ops = [
        PatchOp(op="add", path="/a/1", value=9),
        PatchOp(op="add", path="/a/-", value=3),
        PatchOp(op="replace", path="/b/c", value=2),
        PatchOp.model_validate({"op": "copy", "from": "/b", "path": "/d"}),
        PatchOp.model_validate({"op": "move", "from": "/d/c", "path": "/e"}),
        PatchOp(op="remove", path="/a/0"),
        PatchOp(op="test", path="/e", value=2),
    ]
    assert apply_patch(doc, ops) == {"a": [9, 2, 3], "b": {"c": 2}, "d": {}, "e": 2}
    assert doc == {"a": [1, 2], "b": {"c": 1}}  # 输入不变


@pytest.mark.parametrize(
    "op",
    [
        PatchOp(op="remove", path="/nope"),
        PatchOp(op="replace", path="/a/5", value=1),
        PatchOp(op="test", path="/a/0", value=99),
        PatchOp(op="add", path="", value=1),
        PatchOp(op="add", path="a", value=1),
    ],
)
def test_bad_patch(world: WorldService, op: PatchOp) -> None:
    with pytest.raises(ValidationFailed):
        world.apply({"a": [1]}, [op])


def test_validate(world: WorldService) -> None:
    s = with_entity(world)
    assert world.validate(s, PACK) == []
    bad = world.apply(s, [PatchOp(op="replace", path="/entities/e1/sheet/fields/hp", value=11)])
    assert [p.code for p in world.validate(bad, PACK)] == ["sheet.above_max"]
    bad = world.apply(s, [PatchOp(op="add", path="/controls/p2", value=["e1"])])
    assert [p.code for p in world.validate(bad, PACK)] == ["state.controlled_twice"]
    bad = world.apply(s, [PatchOp(op="add", path="/controls/p2", value=["ghost"])])
    assert [p.code for p in world.validate(bad, PACK)] == ["state.unknown_entity"]
    bad = world.apply(s, [PatchOp(op="add", path="/weather", value="rain")])
    assert [p.code for p in world.validate(bad, PACK)] == ["state.unknown_key"]
    bad = world.apply(s, [PatchOp(op="replace", path="/entities/e1/template", value="zz")])
    assert [p.code for p in world.validate(bad, PACK)] == ["state.unknown_template"]


def test_expire(world: WorldService) -> None:
    s = with_entity(world)
    s = world.apply(
        s,
        [
            PatchOp(
                op="add", path="/entities/e1/sheet/statuses/-", value={"tag": "a", "expires_at": 30}
            ),
            PatchOp(op="add", path="/entities/e1/sheet/statuses/-", value={"tag": "b"}),
            PatchOp(
                op="add", path="/entities/e1/sheet/statuses/-", value={"tag": "c", "expires_at": 60}
            ),
        ],
    )
    assert world.expire(s, 10) == []
    ops = world.expire(s, 60)
    after = world.apply(s, ops)
    entities = after["entities"]
    assert isinstance(entities, dict)
    e1 = entities["e1"]
    assert isinstance(e1, dict)
    sheet = e1["sheet"]
    assert isinstance(sheet, dict)
    assert sheet["statuses"] == [{"tag": "b"}]


def test_canonical_is_stable(world: WorldService) -> None:
    a = world.canonical({"b": 1, "a": {"y": 2, "x": 1}})
    b = world.canonical({"a": {"x": 1, "y": 2}, "b": 1})
    assert a == b
