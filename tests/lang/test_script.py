import pytest

from smartkeeper.lang import Branch, FormulaError, If, Statement, parse_script, statements


def test_statements_lines_and_comments() -> None:
    text = """
# 吸血
target.damage(2d6 + this.level)   # 打对方
self.add(hp, 5); target.sub(mp, max(1, 2))
target.modify(move_speed,
              move_speed * 0.5, 10)
pass
"""
    got = parse_script(text)
    assert got == (
        Statement(line=3, receiver="target", verb="damage", amount="2d6 + this.level"),
        Statement(line=4, receiver="self", verb="add", field="hp", amount="5"),
        Statement(line=4, receiver="target", verb="sub", field="mp", amount="max(1, 2)"),
        Statement(
            line=5,
            receiver="target",
            verb="modify",
            field="move_speed",
            formula="move_speed * 0.5",
            minutes="10",
        ),
    )


def test_optional_minutes_and_strings() -> None:
    (st,) = parse_script('target.add(shield, 3 if this.kind == "a;b" else 1, 60)')
    assert isinstance(st, Statement)
    assert st.minutes == "60"
    assert st.amount == '3 if this.kind == "a;b" else 1'
    assert parse_script("  \n# nothing\n") == ()


@pytest.mark.parametrize(
    ("text", "code", "line"),
    [
        ("target.damage 5", "formula.syntax", 1),
        ("\nfoe.damage(5)", "script.unknown_receiver", 2),
        ("self.heal(5)", "script.unknown_verb", 1),
        ("damage(5)", "script.bad_statement", 1),
        ("x = 5", "script.bad_statement", 1),
        ("self.hp", "script.bad_statement", 1),
        ("self.add(hp)", "script.arity", 1),
        ("self.damage(1, 2)", "script.arity", 1),
        ("self.damage(amount=2)", "script.arity", 1),
        ("target.add(target.hp, 1)", "script.field_arg", 1),
        ("self.damage(1 +)", "formula.syntax", 1),
        ("\nself.damage(x[1])", "formula.unsupported", 2),
        ("self.damage(1)\n  self.damage(2)", "script.unexpected_indent", 2),
        ("if hp > 1:\nself.damage(1)", "script.empty_block", 1),
        ("self.damage(1)\nelse:\n  self.damage(2)", "formula.syntax", 2),
        ("if hp >:\n  self.damage(1)", "formula.syntax", 1),
        ("if hp > 1:\n    self.damage(1)\n  self.damage(2)", "script.unexpected_indent", 3),
        ("if hp = 1:\n  self.damage(1)", "formula.single_equals", 1),
        ("\n\nif hp > 1:\n  self.damage(foo(1))", "formula.unknown_function", 4),
        ("\nif foo(1):\n  pass", "formula.unknown_function", 2),
    ],
)
def test_errors_carry_the_line(text: str, code: str, line: int) -> None:
    with pytest.raises(FormulaError) as err:
        parse_script(text)
    assert err.value.code == code
    assert err.value.params["line"] == line


def test_if_elif_else_blocks() -> None:
    text = """
if target.template == "monster":
    target.add(mp, 2 * this.mp_spent)   # 怪物
    if 1 > 0: self.damage(1)
elif target.template == "boss":
    target.add(mp, this.mp_spent)
else:
    self.add(mp, this.mp_spent)
self.sub(mp, 1)
"""
    got = parse_script(text)
    assert got == (
        If(
            line=2,
            branches=(
                Branch(
                    line=2,
                    condition='target.template == "monster"',
                    body=(
                        Statement(
                            line=3,
                            receiver="target",
                            verb="add",
                            field="mp",
                            amount="2 * this.mp_spent",
                        ),
                        If(
                            line=4,
                            branches=(
                                Branch(
                                    line=4,
                                    condition="1 > 0",
                                    body=(
                                        Statement(
                                            line=4, receiver="self", verb="damage", amount="1"
                                        ),
                                    ),
                                ),
                            ),
                        ),
                    ),
                ),
                Branch(
                    line=5,
                    condition='target.template == "boss"',
                    body=(
                        Statement(
                            line=6,
                            receiver="target",
                            verb="add",
                            field="mp",
                            amount="this.mp_spent",
                        ),
                    ),
                ),
                Branch(
                    line=8,
                    condition=None,
                    body=(
                        Statement(
                            line=8, receiver="self", verb="add", field="mp", amount="this.mp_spent"
                        ),
                    ),
                ),
            ),
        ),
        Statement(line=9, receiver="self", verb="sub", field="mp", amount="1"),
    )
    assert len(statements(got)) == 5


def test_if_after_if_starts_a_new_block_and_tabs_indent() -> None:
    got = parse_script("if 1:\n\tself.damage(1)\nif 0:\n\tself.damage(2)\nelse:\n\tself.damage(3)")
    assert [type(n) for n in got] == [If, If]
    assert [len(n.branches) for n in got if isinstance(n, If)] == [1, 2]
