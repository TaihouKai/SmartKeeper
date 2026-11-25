"""常驻加成的代码：和技能脚本同一种写法，只是一直生效。

    self.move_speed *= 1.2                    # 改数值：= += -= *= /=，# 后面是说明
    if self.template == "master":             # 条件：不成立时这一条不加
        self.str += 2
    else:
        self.str += 1
    bonus = this.level * 2                    # 局部变量
    self.cha += bonus
    # 让人心生畏惧                            # 只有说明的一行：由 KP 理解

只能改自己（self.）的数值，不能有动作（伤害、召唤……），也不能限时（一直生效）。
解析成一串加成：(行号, 改哪个名字, 新值的公式, 说明)。公式里这个名字自己是到上一条为止的值，
条件写进公式（成立时是新值，不成立时是原值）。说明只有文字、没有名字的是由 KP 理解的加成。
"""

from __future__ import annotations

from dataclasses import dataclass

from smartkeeper.lang.formula import FormulaError, Node, parse, substitute, to_text
from smartkeeper.lang.script import If, Let, ScriptNode, Statement, parse_script


@dataclass(frozen=True, slots=True)
class BonusLine:
    line: int
    target: str | None  # 改哪个名字；只有说明的是 None
    formula: str | None
    description: str = ""


def _comments(text: str) -> dict[int, tuple[str, bool]]:
    """每行 # 后面的说明（引号里的 # 不算）：行号 -> (说明, 这一行是不是只有说明)。"""
    out: dict[int, tuple[str, bool]] = {}
    for i, raw in enumerate(text.split("\n"), start=1):
        quote = ""
        j = 0
        while j < len(raw):
            c = raw[j]
            if quote:
                if c == "\\":
                    j += 1
                elif c == quote:
                    quote = ""
            elif c in "\"'":
                quote = c
            elif c == "#":
                note = raw[j + 1 :].strip()
                if note:
                    out[i] = (note, not raw[:j].strip())
                break
            j += 1
    return out


def parse_bonus(text: str) -> tuple[BonusLine, ...]:
    """解析失败抛 FormulaError（带 line）。"""
    notes = _comments(text)
    nodes = parse_script(text)
    env: dict[str, Node] = {}
    found: list[BonusLine] = []

    def expand(formula: str, line: int) -> str:
        try:
            node = substitute(parse(formula), lambda n: env.get(n))
        except FormulaError as e:
            raise FormulaError(e.code, **{"line": line, **e.params}) from None
        return to_text(node)

    def walk(body: tuple[ScriptNode, ...], cond: str | None) -> None:
        for n in body:
            if isinstance(n, Let):
                env[n.name] = parse(expand(n.value, n.line))
                continue
            if isinstance(n, If):
                earlier: list[str] = []
                for b in n.branches:
                    here = [f"not ({c})" for c in earlier]
                    if b.condition is not None:
                        c = expand(b.condition, b.line)
                        here.append(f"({c})")
                        earlier.append(c)
                    if cond is not None:
                        here.insert(0, f"({cond})")
                    walk(b.body, " and ".join(here) if here else cond)
                continue
            st: Statement = n
            if st.verb != "change":
                raise FormulaError("bonus.no_action", line=st.line, name=st.verb)
            if st.minutes is not None:
                raise FormulaError("bonus.no_minutes", line=st.line)
            if st.receiver != "self" or not st.field or st.field.startswith("this."):
                raise FormulaError("bonus.self_only", line=st.line)
            assert st.amount is not None and st.op is not None
            name = st.field
            value = expand(st.amount, st.line)
            new = value if st.op == "=" else f"{name} {st.op[0]} ({value})"
            if cond is not None:
                new = f"({new}) if ({cond}) else {name}"
            note = notes.get(st.line, ("", False))[0]
            found.append(BonusLine(st.line, name, to_text(parse(new)), note))

    walk(nodes, None)
    for line, (note, alone) in notes.items():
        if alone:
            found.append(BonusLine(line, None, None, note))
    return tuple(sorted(found, key=lambda b: b.line))
