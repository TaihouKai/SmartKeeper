"""名字保密的角色：游戏页上自己看到的是代号（没填按指定的字段），名字（例如真名）可以作为情报给出去。"""

from __future__ import annotations

from smartkeeper.contracts import IntelIn, PatchOp
from tests.engine.harness import setup_table
from tests.engine.test_timeline import publish
from tests.engine.test_uses import begin
from tests.fixtures import load_pack


def secret_pack():  # type: ignore[no-untyped-def]
    base = load_pack("single")
    tpl = base.templates[0].model_copy(
        update={"name_secret": True, "alias_label": "Alias", "alias_from": "occupation"}
    )
    return base.model_copy(update={"templates": (tpl, *base.templates[1:])})


def test_secret_name_shows_the_alias() -> None:
    t = setup_table("single", 2, pack=secret_pack())
    e, g = t.engine, t.game_id
    p0, p1 = t.players
    a, b = t.entities(p0)[0], t.entities(p1)[0]
    occupation = e.world_state(g)["entities"][a]["sheet"]["fields"]["occupation"]  # type: ignore[index]
    # 没填代号：用职业
    assert e.scene(g, p0).entities[0].name == occupation
    assert e.sheets(g, p0)[0].label == occupation
    # 填了代号就用代号
    e.admin_patch(g, [PatchOp(op="add", path=f"/entities/{a}/sheet/alias", value="Fox")])
    assert e.scene(g, p0).entities[0].name == "Fox"
    # 名字可以作为情报给别人（例如真名暴露）
    real = e.world_state(g)["entities"][a]["sheet"]["name"]  # type: ignore[index]
    begin(t)
    publish(t, only=t.players, intel=[IntelIn(player=p1, about=a, fields=("name",))])
    facts = e.player_intel(g, p1).get(a, ())
    assert any(
        f.kind == "field" and f.field and f.field.name == "name" and f.field.value == real
        for f in facts
    )
    assert b  # 另一个玩家照常
