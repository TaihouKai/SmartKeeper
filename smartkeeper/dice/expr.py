"""骰子表达式：若干项用 + / - 连接，每项是 NdM、dM 或整数常量。例如 1d100、3d6+2、2d6-1d4+1。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from smartkeeper.contracts import Problem

MAX_DICE = 1000
MAX_SIDES = 100000

_TERM = re.compile(r"([+-]?)(?:(\d*)[dD](\d+)|(\d+))")


@dataclass(frozen=True, slots=True)
class Term:
    sign: int
    count: int  # 0 表示常量项
    sides: int
    constant: int


def parse(expr: str) -> list[Term]:
    """解析失败抛 ValueError。"""
    text = expr.replace(" ", "")
    if not text:
        raise ValueError("empty")
    terms: list[Term] = []
    pos = 0
    while pos < len(text):
        m = _TERM.match(text, pos)
        if not m or m.end() == pos:
            raise ValueError(f"bad token at {pos}")
        sign_s, count_s, sides_s, const_s = m.groups()
        if not sign_s and terms:
            raise ValueError(f"missing operator at {pos}")
        sign = -1 if sign_s == "-" else 1
        if sides_s is not None:
            count = int(count_s) if count_s else 1
            sides = int(sides_s)
            if not (1 <= count <= MAX_DICE) or not (1 <= sides <= MAX_SIDES):
                raise ValueError("dice out of range")
            terms.append(Term(sign, count, sides, 0))
        else:
            terms.append(Term(sign, 0, 0, int(const_s)))
        pos = m.end()
    return terms


def validate(expr: str) -> list[Problem]:
    try:
        parse(expr)
    except ValueError as e:
        return [Problem(code="dice.invalid", params={"expr": expr, "reason": str(e)})]
    return []


def bounds(expr: str) -> tuple[int, int]:
    lo = hi = 0
    for t in parse(expr):
        if t.count:
            a, b = t.count, t.count * t.sides
        else:
            a = b = t.constant
        if t.sign > 0:
            lo, hi = lo + a, hi + b
        else:
            lo, hi = lo - b, hi - a
    return lo, hi
