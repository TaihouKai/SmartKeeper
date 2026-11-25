"""统一的写法：改数值用 = += -= *= /=，限时写在 with minutes(…) 里，常驻加成也是同一种代码。"""

from __future__ import annotations

import pytest

from smartkeeper import lang as f

RUNTIME = {"hp", "mp", "shield"}


def lowered(text: str) -> list[tuple[str, str, str | None, str | None, str | None, str | None]]:
    return [
        (s.receiver, s.verb, s.field, s.amount, s.formula, s.minutes)
        for s in f.statements(f.lower(f.parse_script(text), RUNTIME))
    ]


def test_changes_become_the_old_actions() -> None:
    assert lowered("self.mp -= this.mp_spent\ntarget.hp += 2d6\ntarget.hp = target.hp_max") == [
        ("self", "sub", "mp", "this.mp_spent", None, None),
        ("target", "add", "hp", "2d6", None, None),
        ("target", "set", "hp", "target.hp_max", None, None),
    ]
    assert lowered("target.hp *= 0.5")[0][:4] == ("target", "set", "hp", "target.hp * (0.5)")
    assert lowered("this.on = 1") == [("self", "set", "this.on", "1", None, None)]


def test_minutes_block_is_timed() -> None:
    text = "with minutes(10):\n    target.str -= 2\n    target.move_speed *= 0.5\n    target.shield += 10\n    target.mp -= 3"
    assert lowered(text) == [
        ("target", "modify", "str", None, "target.str - (2)", "10"),
        ("target", "modify", "move_speed", None, "target.move_speed * (0.5)", "10"),
        ("target", "add", "shield", "10", None, "10"),
        ("target", "add", "mp", "-(3)", None, "10"),
    ]


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("target.str -= 2", "script.needs_minutes"),  # 属性不能直接改
        ("with minutes(5):\n    target.hp = 1", "script.timed_runtime"),
        ("with minutes(5):\n    target.damage(1)", "script.action_in_minutes"),
        ("with open(5):\n    target.hp += 1", "script.bad_with"),
    ],
)
def test_wrong_uses_are_explained(text: str, code: str) -> None:
    with pytest.raises(f.FormulaError) as err:
        f.lower(f.parse_script(text), RUNTIME)
    assert err.value.code == code


def test_bonus_code_with_conditions_variables_and_notes() -> None:
    text = (
        "self.move_speed *= 1.2   # 快\n"
        'if self.template == "master":\n'
        "    self.str += 2\n"
        "else:\n"
        "    self.str += 1\n"
        "b = this.level * 2\n"
        "self.cha += b\n"
        "# 让人心生畏惧\n"
    )
    got = [(b.line, b.target, b.formula, b.description) for b in f.parse_bonus(text)]
    assert got == [
        (1, "move_speed", "move_speed * 1.2", "快"),
        (3, "str", 'str + 2 if self.template == "master" else str', ""),
        (5, "str", 'str + 1 if not self.template == "master" else str', ""),
        (7, "cha", "cha + this.level * 2", ""),
        (8, None, None, "让人心生畏惧"),
    ]


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("target.str += 1", "bonus.self_only"),
        ("self.damage(1)", "bonus.no_action"),
        ("with minutes(5):\n    self.str += 1", "bonus.no_minutes"),
    ],
)
def test_bonus_code_limits(text: str, code: str) -> None:
    with pytest.raises(f.FormulaError) as err:
        f.parse_bonus(text)
    assert err.value.code == code


def test_clock_literals() -> None:
    """14:00 是小时数 14，14:30 是 14.5；和 time 比较。"""
    assert f.to_text(f.parse("time < 14:00 and time > 10:30")) == "time < 14 and time > 10.5"
    assert f.desugar('if time >= 22:00:\n    x = "12:00"') == 'if time >= 22.0:\n    x = "12:00"'
    assert f.desugar("with minutes(10):") == "with minutes(10):"
