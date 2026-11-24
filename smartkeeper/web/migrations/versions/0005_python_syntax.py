"""formulas and scripts switch to Python syntax: if(c, a, b) -> a if c else b, and(a, b) -> a and b,
x = 1 -> x == 1, a d b -> dice(a, b). Only text the new parser can't read (or reads differently) changes.

Revision ID: 0005
Revises: 0004
"""

# ruff: noqa
# pyright: basic
import json
import re
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from alembic import op

from smartkeeper.lang import Binary, Call, Dice, FormulaError, Name, Node, Num, Str, Unary
from smartkeeper.lang import parse as new_parse
from smartkeeper.lang import parse_script as new_parse_script
from smartkeeper.lang import to_text

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None

COLUMNS = [
    ('rule_pack_draft', 'body'),
    ('rule_pack_version', 'body'),
    ('event', 'payload'),
    ('round', 'snapshot'),
    ('round', 'draft'),
    ('round', 'submitted'),
    ('game', 'settings'),
]
FORMULA_KEYS = {
    'formula', 'amount', 'when', 'cast_time', 'cooldown', 'min', 'max', 'initial', 'radius',
    'perceive_multiplier', 'charges', 'duration', 'per_minute', 'condition', 'dice', 'target',
}
COMPARISONS = ("<", "<=", ">", ">=", "==", "!=")

# ---------------- 旧的公式解析器（0004 时的写法），原样保留 ----------------

_OLD_FUNCTIONS: dict[str, tuple[int, int | None]] = {
    "abs": (1, 1),
    "floor": (1, 1),
    "ceil": (1, 1),
    "round": (1, 1),
    "trunc": (1, 1),
    "sign": (1, 1),
    "sqrt": (1, 1),
    "pow": (2, 2),
    "mod": (2, 2),
    "min": (1, None),
    "max": (1, None),
    "clamp": (3, 3),
    "if": (3, 3),
    "and": (1, None),
    "or": (1, None),
    "not": (1, 1),
    "lookup": (2, 2),
    "count": (1, 2),
    "sum": (1, 1),
    "highest": (3, 3),
    "lowest": (3, 3),
}
LIST_FUNCTIONS = ("count", "sum")

_TOKEN = re.compile(
    r"\s*(?:(?P<num>\d+(?:\.\d+)?)|(?P<str>\"[^\"]*\")|(?P<name>[^\W\d]\w*(?:\.[^\W\d]\w*)*)"
    r"|(?P<op><=|>=|==|!=|[-+*/()<>,%=]))"
)
_DIE_NAME = re.compile(r"[dD](\d*)")


@dataclass(frozen=True, slots=True)
class _Tok:
    kind: str
    text: str
    pos: int

    def is_op(self, *ops: str) -> bool:
        return self.kind == "op" and self.text in ops


def _tokenize(text: str) -> list[_Tok]:
    tokens: list[_Tok] = []
    pos = 0
    text = text.rstrip()
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            raise FormulaError("formula.bad_token", pos=pos)
        kind = m.lastgroup
        assert kind is not None
        start = m.start(kind)
        word = m.group(kind)
        prev = tokens[-1] if tokens else None
        glued = prev is not None and prev.kind == "num" and start == prev.pos + len(prev.text)
        if kind == "name" and (glued or _DIE_NAME.fullmatch(word)) and word[0] in "dD":
            # 3d6、1dstr：数字后紧跟的 d；d、d20：单独的 d 或 d 加数字
            tokens.append(_Tok("op", "d", start))
            rest = word[1:]
            if rest:
                tokens.append(_Tok("num" if rest.isdigit() else "name", rest, start + 1))
        else:
            tokens.append(_Tok(kind, word, start))
        pos = m.end()
    return tokens


class _Parser:
    def __init__(self, text: str) -> None:
        self.tokens = _tokenize(text)
        self.i = 0

    def peek(self) -> _Tok | None:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def peek_op(self, *ops: str) -> bool:
        tok = self.peek()
        return tok is not None and tok.is_op(*ops)

    def take(self) -> _Tok:
        tok = self.peek()
        if tok is None:
            raise FormulaError("formula.unexpected_end")
        self.i += 1
        return tok

    def expect(self, op: str) -> None:
        tok = self.take()
        if not tok.is_op(op):
            raise FormulaError("formula.expected", token=op, pos=tok.pos)

    def parse(self) -> Node:
        if not self.tokens:
            raise FormulaError("formula.empty")
        node = self.comparison()
        tok = self.peek()
        if tok is not None:
            raise FormulaError("formula.trailing", pos=tok.pos)
        return node

    def comparison(self) -> Node:
        left = self.additive()
        if self.peek_op(*COMPARISONS, "="):
            op = self.take().text
            left = Binary("==" if op == "=" else op, left, self.additive())
            if self.peek_op(*COMPARISONS, "="):
                raise FormulaError("formula.chained_comparison")
        return left

    def additive(self) -> Node:
        left = self.term()
        while self.peek_op("+", "-"):
            op = self.take().text
            left = Binary(op, left, self.term())
        return left

    def term(self) -> Node:
        left = self.unary()
        while self.peek_op("*", "/"):
            op = self.take().text
            left = Binary(op, left, self.unary())
        return left

    def unary(self) -> Node:
        if self.peek_op("-"):
            self.take()
            return Unary("-", self.unary())
        return self.dice()

    def dice(self) -> Node:
        if self.peek_op("d"):
            self.take()
            node: Node = Dice(Num(1), self.sides())
        else:
            node = self.primary()
        while self.peek_op("d"):
            self.take()
            node = Dice(node, self.sides())
        return node

    def sides(self) -> Node:
        if self.peek_op("%"):
            self.take()
            return Num(100)
        return self.primary()

    def primary(self) -> Node:
        tok = self.take()
        if tok.kind == "num":
            return Num(float(tok.text))
        if tok.kind == "str":
            return Str(tok.text[1:-1])
        if tok.kind == "name":
            if self.peek_op("("):
                return self.call(tok)
            return Name(tok.text)
        if tok.is_op("("):
            node = self.comparison()
            self.expect(")")
            return node
        raise FormulaError("formula.unexpected", token=tok.text, pos=tok.pos)

    def call(self, tok: _Tok) -> Node:
        name = tok.text
        if name not in _OLD_FUNCTIONS:
            raise FormulaError("formula.unknown_function", name=name)
        self.expect("(")
        args: list[Node] = []
        if not self.peek_op(")"):
            args.append(self.comparison())
            while self.peek_op(","):
                self.take()
                args.append(self.comparison())
        self.expect(")")
        lo, hi = _OLD_FUNCTIONS[name]
        if len(args) < lo or (hi is not None and len(args) > hi):
            raise FormulaError("formula.arity", name=name, count=len(args))
        if name == "lookup" and not isinstance(args[0], Name):
            raise FormulaError("formula.lookup_table_name")
        if name in LIST_FUNCTIONS and not isinstance(args[0], Name):
            raise FormulaError("formula.list_ref", name=name)
        return Call(name, tuple(args))


def old_parse(text: str) -> Node:
    return _Parser(text).parse()


# ---------------- 旧的脚本切分 ----------------

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


_HEADER = re.compile(r"^(if|elif)(?=[\s(])(.*):$|^else\s*:$", re.DOTALL)
_STMT = re.compile(r"^(\w+)\.(\w+)\((.*)\)$", re.DOTALL)


def formula(text: str) -> str:
    """旧写法 -> 新写法；新解析器读出来意思一样（或者旧解析器也读不了）就不动。"""
    if not text.strip():
        return text
    try:
        old = old_parse(text)
    except FormulaError:
        return text
    try:
        if new_parse(text) == old:
            return text
    except FormulaError:
        pass
    return to_text(old)


def _comment(line: str) -> str:
    """一行里引号外面的 # 注释（带前面的空格）；没有就是空。"""
    quoted = False
    for i, c in enumerate(line):
        if c == '"':
            quoted = not quoted
        elif c == '#' and not quoted:
            return '  ' + line[i:].strip()
    return ''


def _comment(line: str) -> str:
    """一行里引号外面的 # 注释（带前面的空格）；没有就是空。"""
    quoted = False
    for i, c in enumerate(line):
        if c == '"':
            quoted = not quoted
        elif c == '#' and not quoted:
            return '  ' + line[i:].strip()
    return ''


def script(text: str) -> str:
    """新写法读得了就不动；否则一句一句改写。空行和注释保留（行尾注释跟着那一句的第一行）。"""
    try:
        new_parse_script(text)
        return text
    except FormulaError:
        pass
    starts: dict[int, list[str]] = {}
    indent_of: dict[int, int] = {}
    for line, indent, stmt in _split(text):
        m = _HEADER.match(stmt)
        if m:
            new = f"{m.group(1)} {formula(m.group(2).strip())}:" if m.group(1) else 'else:'
        else:
            m = _STMT.match(stmt)
            if m:
                args = [formula(x) for x in _args(m.group(3))] if m.group(3).strip() else []
                new = f"{m.group(1)}.{m.group(2)}({', '.join(args)})"
            else:
                new = stmt
        starts.setdefault(line, []).append(new)
        indent_of.setdefault(line, indent)
    out: list[str] = []
    for i, raw in enumerate(text.split('\n'), start=1):
        if i in starts:
            out.append(' ' * indent_of[i] + '; '.join(starts[i]) + _comment(raw))
        elif not raw.strip() or raw.strip().startswith('#'):
            out.append(raw)  # 空行、注释行
        # 其余是上一句没写完、接着写的行：已经并进那一句了
    return '\n'.join(out).rstrip('\n') + ('\n' if text.endswith('\n') else '')


def convert(obj: Any, key: str = '') -> Any:
    """返回转换后的对象（就地修改字典和列表）。"""
    if isinstance(obj, str):
        if key == 'script':
            return script(obj)
        return formula(obj) if key in FORMULA_KEYS else obj
    if isinstance(obj, list):
        return [convert(x) for x in obj]
    if isinstance(obj, dict):
        for k in list(obj):
            v = obj[k]
            if k == 'fields' and isinstance(v, dict):
                obj[k] = {fk: convert(fv, 'formula') for fk, fv in v.items()}  # 掷骰公式列
            else:
                obj[k] = convert(v, k)
    return obj


def upgrade() -> None:
    conn = op.get_bind()
    for table, col in COLUMNS:
        rows = conn.execute(
            sa.text(f'SELECT rowid, {col} FROM {table} WHERE {col} IS NOT NULL')
        ).fetchall()
        for rowid, raw in rows:
            try:
                data = json.loads(raw)
            except (TypeError, ValueError):
                continue
            new = json.dumps(convert(data), ensure_ascii=False)
            if new != json.dumps(json.loads(raw), ensure_ascii=False):
                conn.execute(
                    sa.text(f'UPDATE {table} SET {col} = :v WHERE rowid = :r'),
                    {'v': new, 'r': rowid},
                )


def downgrade() -> None:
    raise NotImplementedError('公式不能自动转回旧写法')
