import pytest

from smartkeeper.lang import FormulaError, Statement, parse_script


def test_statements_lines_and_comments() -> None:
    text = """
    # 吸血
    target.damage(2d6 + this.level)   # 打对方
    self.add(hp, 5); target.sub(mp, max(1, 2))
    target.modify(move_speed,
                  move_speed * 0.5, 10)
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
    (st,) = parse_script('target.add(shield, if(this.kind = "a;b", 3, 1), 60)')
    assert st.minutes == "60"
    assert st.amount == 'if(this.kind = "a;b", 3, 1)'
    assert parse_script("  \n# nothing\n") == ()


@pytest.mark.parametrize(
    ("text", "code", "line"),
    [
        ("target.damage 5", "script.bad_statement", 1),
        ("\nfoe.damage(5)", "script.unknown_receiver", 2),
        ("self.heal(5)", "script.unknown_verb", 1),
        ("self.add(hp)", "script.arity", 1),
        ("self.damage(1, 2)", "script.arity", 1),
        ("target.add(target.hp, 1)", "script.field_arg", 1),
        ("self.damage(1 +)", "formula.unexpected_end", 1),
    ],
)
def test_errors_carry_the_line(text: str, code: str, line: int) -> None:
    with pytest.raises(FormulaError) as err:
        parse_script(text)
    assert err.value.code == code
    assert err.value.params["line"] == line
