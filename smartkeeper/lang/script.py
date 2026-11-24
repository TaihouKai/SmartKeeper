"""技能脚本：用技能时执行的一串语句。

    target.damage(2d6 + this.level)          # 受到伤害（先扣护盾再扣生命值，由调用方决定怎么扣）
    self.add(hp, 5)                          # 加；第三个参数是持续分钟数，到期扣回剩下的部分
    target.sub(mp, 10); target.set(stance, 0)
    target.modify(move_speed, move_speed * 0.5, 10)   # 限时修正：推导值的新值公式，持续分钟数

    if target.template == "monster":         # 条件分支：缩进的几行是它的内容
        target.add(mp, 2 * this.mp_spent)
    elif target.template == "boss":
        target.add(mp, this.mp_spent)
    else:
        self.add(mp, this.mp_spent)

- 一行一句，也可以用 ; 隔开；括号没关上时可以换行接着写；# 后面是注释。
- 每句是 <对象>.<动作>(参数, ...)。对象：self 是使用者自己，target 是使用时选的对象（也可以是自己）。
- 字段参数写名字；其余参数和条件是公式（见 formula.py）。
- if / elif / else 后面写冒号，下面缩进的几行是这一支（缩进多少都行，同一支里要对齐）；可以套着写。

这里只管语法：解析出语句，参数保留原文，由调用方在自己的上下文里求值。
"""

from __future__ import annotations

import re
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
    """一句动作。"""

    line: int  # 从 1 开始
    receiver: Receiver
    verb: str
    field: str | None = None
    amount: str | None = None
    formula: str | None = None
    minutes: str | None = None


@dataclass(frozen=True, slots=True)
class Branch:
    """if / elif / else 的一支。condition 是公式原文；else 的是 None。"""

    line: int
    condition: str | None
    body: tuple[ScriptNode, ...]


@dataclass(frozen=True, slots=True)
class If:
    """条件分支：从上往下第一个条件成立的一支执行；都不成立时执行 else（有的话）。"""

    line: int
    branches: tuple[Branch, ...]


type ScriptNode = Statement | If


def _split(text: str) -> list[tuple[int, int, str]]:
    """切成语句：(起始行号, 起始行的缩进, 原文)。字符串里和括号里的 ; 与换行不算分隔，# 到行尾是注释。"""
    indents = [len(x) - len(x.lstrip(" ")) for x in text.expandtabs(4).split("\n")]
    out: list[tuple[int, int, str]] = []
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
                out.append((start, indents[start - 1], "".join(buf).strip()))
            buf = []
            start = line
            continue
        if not "".join(buf).strip():
            start = line
        buf.append(" " if ch == "\n" else ch)
    if "".join(buf).strip():
        out.append((start, indents[start - 1], "".join(buf).strip()))
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


_HEADER = re.compile(r"^(if|elif)(?=[\s(])(.*):$|^else\s*:$", re.DOTALL)


def _header(line: int, text: str) -> tuple[str, str | None] | None:
    """if / elif / else 行：(关键字, 条件原文)；不是的话 None。"""
    m = _HEADER.match(text)
    if m is None:
        return None
    if m.group(1) is None:
        return "else", None
    cond = m.group(2).strip()
    if not cond:
        raise FormulaError("script.bad_condition", line=line, text=text)
    try:
        parse(cond)
    except FormulaError as e:
        raise FormulaError(e.code, line=line, **e.params) from e
    return m.group(1), cond


type _Item = tuple[int, int, str]


def _block(items: list[_Item], i: int, indent: int) -> tuple[tuple[ScriptNode, ...], int]:
    """从第 i 句起读缩进为 indent 的一段，读到缩进变小为止。返回 (语句, 下一句的位置)。"""
    out: list[ScriptNode] = []
    while i < len(items):
        line, ind, text = items[i]
        if ind < indent:
            break
        if ind > indent:
            raise FormulaError("script.unexpected_indent", line=line)
        head = _header(line, text)
        if head is None:
            out.append(_statement(line, text))
            i += 1
            continue
        if head[0] != "if":
            raise FormulaError("script.dangling_else", line=line, name=head[0])
        branches: list[Branch] = []
        while True:
            body, i = _body(items, i, indent)
            branches.append(Branch(line=line, condition=head[1], body=body))
            if head[0] == "else" or i >= len(items) or items[i][1] != indent:
                break
            line, _, text = items[i]
            nxt = _header(line, text)
            if nxt is None or nxt[0] == "if":
                break
            head = nxt
        out.append(If(line=branches[0].line, branches=tuple(branches)))
    return tuple(out), i


def _body(items: list[_Item], i: int, indent: int) -> tuple[tuple[ScriptNode, ...], int]:
    """第 i 句是 if / elif / else 行，读它下面缩进更深的一段。"""
    line = items[i][0]
    i += 1
    if i >= len(items) or items[i][1] <= indent:
        raise FormulaError("script.empty_block", line=line)
    return _block(items, i, items[i][1])


def parse_script(text: str) -> tuple[ScriptNode, ...]:
    """解析失败抛 FormulaError，参数里带 line（第几行）。空脚本是空元组。"""
    items = _split(text)
    if not items:
        return ()
    nodes, _ = _block(items, 0, min(ind for _, ind, _ in items))
    return nodes


def statements(nodes: tuple[ScriptNode, ...]) -> list[Statement]:
    """所有的动作句，包括各个分支里的。"""
    out: list[Statement] = []
    for n in nodes:
        if isinstance(n, Statement):
            out.append(n)
        else:
            for b in n.branches:
                out += statements(b.body)
    return out
