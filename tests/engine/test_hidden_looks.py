"""看不清样子：模板的 appearance_hidden 成立时，别人拿不到外观（起外号、KP 的反馈、被攻击时的提示），自己照样看得到。"""

from __future__ import annotations

from smartkeeper.rules import RulesService
from tests.engine.harness import setup_table
from tests.fixtures import load_pack


def test_hidden_looks_are_not_given_to_others() -> None:
    base = load_pack("single")
    tpl = base.templates[0]
    pack = base.model_copy(
        update={
            "templates": (tpl.model_copy(update={"appearance_hidden": "1"}), *base.templates[1:])
        }
    )
    assert RulesService().validate_pack(pack) == []
    t = setup_table("single", 2, pack=pack)
    e, g = t.engine, t.game_id
    p0, _p1 = t.players
    mine, theirs = t.entities(p0)[0], t.entities(t.players[1])[0]
    real = e.appearance_of(g, theirs, by_others=False)
    assert real and e.appearance_of(g, theirs) != real
    appearance, _labels = e.handle_context(g, p0, theirs)
    assert appearance == e.appearance_of(g, theirs) != real
    assert e.appearance_of(g, mine, by_others=False) != e.appearance_of(g, mine)


def test_a_bad_hidden_formula_is_a_rulebook_problem() -> None:
    base = load_pack("single")
    tpl = base.templates[0]
    pack = base.model_copy(
        update={
            "templates": (
                tpl.model_copy(update={"appearance_hidden": "no_such_field"}),
                *base.templates[1:],
            )
        }
    )
    assert RulesService().validate_pack(pack)
