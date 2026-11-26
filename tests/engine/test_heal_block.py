"""加不上去的条件：被禁止治疗的角色，技能脚本给它加的生命值无效（减少照常）；没被禁止的照常加。"""

from __future__ import annotations

from smartkeeper.contracts import DerivedDef, GroupPreset, RulePack, UseResult
from smartkeeper.rules import RulesService
from tests.engine.harness import setup_table
from tests.engine.test_timeline import fields_of, publish
from tests.engine.test_uses import begin
from tests.fixtures import load_pack


def pack() -> RulePack:
    base = load_pack("single")
    tpl = base.templates[0]
    fields = tuple(
        f.model_copy(update={"gain_blocked": "heal_blocked > 0"}) if f.name == "hp" else f
        for f in tpl.fields
    )
    g = tpl.groups[0]
    presets = (
        GroupPreset(name="zap", fields={"level": 1}, script="target.damage(2)"),
        GroupPreset(
            name="hex",
            fields={"level": 1},
            script="with minutes(60):\n    target.heal_blocked += 1",
        ),
        GroupPreset(name="mend", fields={"level": 1}, script="target.hp += 1"),
    )
    tpl = tpl.model_copy(
        update={
            "fields": fields,
            "derived": (*tpl.derived, DerivedDef(name="heal_blocked", formula="0")),
            "groups": (g.model_copy(update={"presets": (*g.presets, *presets)}), *tpl.groups[1:]),
        }
    )
    return base.model_copy(update={"templates": (tpl, *base.templates[1:])})


def test_blocked_healing_does_nothing() -> None:
    p = pack()
    assert RulesService().validate_pack(p) == []
    t = setup_table("single", 2, pack=p)
    a, b = (t.entities(x)[0] for x in t.players)
    e, g = t.engine, t.game_id
    full = fields_of(t, b)["hp"]
    assert isinstance(full, int | float)

    def use(entry: str, target: str) -> None:
        begin(t)
        u = e.use_entry(g, a, entry, target, {}, "x")
        publish(t, only=t.players, uses=[UseResult(seq=u.seq)])

    use("zap", b)
    use("zap", a)
    use("hex", b)
    use("mend", b)  # 被禁止治疗：加不上去
    assert fields_of(t, b)["hp"] == full - 2
    use("mend", a)  # 没被禁止：照常
    assert fields_of(t, a)["hp"] == full - 1
    use("zap", b)  # 减少照常
    assert fields_of(t, b)["hp"] == full - 4
