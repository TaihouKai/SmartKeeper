"""技能脚本：用技能时执行的一串语句。

    target.damage(2d6 + this.level)          # 受到伤害（先扣护盾再扣生命值，由调用方决定怎么扣）
    self.add(hp, 5)                          # 加；第三个参数是持续分钟数，到期扣回剩下的部分
    target.sub(mp, 10); target.set(stance, 0)
    target.modify(move_speed, move_speed * 0.5, 10)   # 限时修正：推导值的新值公式，持续分钟数

- 一行一句，也可以用 ; 隔开；括号没关上时可以换行接着写；# 后面是注释。
- 每句是 <对象>.<动作>(参数, ...)。对象：self 是使用者自己，target 是使用时选的对象（也可以是自己）。
- 字段参数写名字；其余参数是公式（见 formula.py）。

这里只管语法：解析出语句，参数保留原文，由调用方在自己的上下文里求值。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from smartkeeper.lang.formula import FormulaError, Name, parse

type Receiver = Literal["self", "target"]
RECEIVERS: tuple[Receiver, ...] = ("self", "target")

# 动作 -> 参数：field 是字段名，其余是公式；? 表示可以不写
VERBS: dict[str, tuple[str, ...]] = {
    "damage": ("amount",),
    "add": ("field", "amount", "minutes?"),
    "sub": ("field", "amount"),
    "set": ("field", "amount"),
    "modify": ("field", "formula", "minutes"),
}


@dataclass(frozen=True, slots=True)
class Statement:
    line: int  # 从 1 开始
    receiver: Receiver
    verb: str
    field: str | None = None
    amount: str | None = None
    formula: str | None = None
    minutes: str | None = None


def _split(text: str) -> list[tuple[int, str]]:
    """切成语句：(起始行号, 原文)。字符串里和括号里的 ; 与换行不算分隔，# 到行尾是注释。"""
    out: list[tuple[int, str]] = []
    buf: list[str] = []
    line = start = 1
    depth = 0
    quoted = False
    comment = False
    for ch in text:
        if ch == "\n":
            line += 1
            comment = False
        if comment:
            continue
        if quoted:
            buf.append(ch)
            quoted = ch != '"'
            continue
        if ch == '"':
            quoted = True
        elif ch == "#":
            comment = True
            continue
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch in ";\n" and depth == 0:
            if "".join(buf).strip():
                out.append((start, "".join(buf).strip()))
            buf = []
            start = line
            continue
        if not "".join(buf).strip():
            start = line
        buf.append(" " if ch == "\n" else ch)
    if "".join(buf).strip():
        out.append((start, "".join(buf).strip()))
    return out


def _args(text: str) -> list[str]:
    """按最外层的逗号切参数。"""
    out: list[str] = []
    depth = 0
    quoted = False
    cur: list[str] = []
    for ch in text:
        if quoted:
            quoted = ch != '"'
        elif ch == '"':
            quoted = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            out.append("".join(cur).strip())
            cur = []
            continue
        cur.append(ch)
    out.append("".join(cur).strip())
    return out


def _statement(line: int, text: str) -> Statement:
    head, paren, rest = text.partition("(")
    head = head.strip()
    if not paren or not rest.rstrip().endswith(")") or "." not in head:
        raise FormulaError("script.bad_statement", line=line, text=text)
    who, _, verb = head.partition(".")
    if who not in RECEIVERS:
        raise FormulaError("script.unknown_receiver", line=line, name=who)
    if verb not in VERBS:
        raise FormulaError("script.unknown_verb", line=line, name=verb)
    inner = rest.rstrip()[:-1]
    args = _args(inner) if inner.strip() else []
    spec = VERBS[verb]
    need = sum(1 for s in spec if not s.endswith("?"))
    if not need <= len(args) <= len(spec) or any(not a for a in args):
        raise FormulaError("script.arity", line=line, name=verb, count=len(args))
    got: dict[str, str] = {}
    for kind, arg in zip(spec, args, strict=False):
        kind = kind.rstrip("?")
        try:
            node = parse(arg)
        except FormulaError as e:
            raise FormulaError(e.code, line=line, **e.params) from e
        if kind == "field" and (not isinstance(node, Name) or "." in node.name):
            raise FormulaError("script.field_arg", line=line, name=verb)
        got[kind] = arg
    return Statement(
        line=line,
        receiver="self" if who == "self" else "target",
        verb=verb,
        field=got.get("field"),
        amount=got.get("amount"),
        formula=got.get("formula"),
        minutes=got.get("minutes"),
    )


def parse_script(text: str) -> tuple[Statement, ...]:
    """解析失败抛 FormulaError，参数里带 line（第几行）。空脚本是空元组。"""
    return tuple(_statement(line, s) for line, s in _split(text))
