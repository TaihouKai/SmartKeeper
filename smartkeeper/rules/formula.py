"""受限的公式语言。

只支持：数字、字符串字面量、四则运算、比较、括号、字段引用（name 或 self.name）、
以及函数 floor / ceil / round / min / max / lookup。引擎不执行任何外部代码，这里是自己的求值器。
比较运算的结果是 1 或 0。
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass

FUNCTIONS: dict[str, tuple[int, int | None]] = {
    "floor": (1, 1),
    "ceil": (1, 1),
    "round": (1, 1),
    "min": (1, None),
    "max": (1, None),
    "lookup": (2, 2),
}

COMPARISONS = ("<", "<=", ">", ">=", "==", "!=")

type Value = float | str


class FormulaError(Exception):
    def __init__(self, code: str, **params: str | int | float) -> None:
        self.code = code
        self.params = params
        super().__init__(f"{code} {params}")


@dataclass(frozen=True, slots=True)
class Num:
    value: float


@dataclass(frozen=True, slots=True)
class Str:
    value: str


@dataclass(frozen=True, slots=True)
class Name:
    name: str  # "x" 或 "self.x"


@dataclass(frozen=True, slots=True)
class Unary:
    op: str
    operand: Node


@dataclass(frozen=True, slots=True)
class Binary:
    op: str
    left: Node
    right: Node


@dataclass(frozen=True, slots=True)
class Call:
    func: str
    args: tuple[Node, ...]


type Node = Num | Str | Name | Unary | Binary | Call

_TOKEN = re.compile(
    r"\s*(?:(?P<num>\d+(?:\.\d+)?)|(?P<str>\"[^\"]*\")|(?P<name>[^\W\d]\w*(?:\.[^\W\d]\w*)?)"
    r"|(?P<op><=|>=|==|!=|[-+*/()<>,]))"
)


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
        tokens.append(_Tok(kind, m.group(kind), m.start(kind)))
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
        if self.peek_op(*COMPARISONS):
            op = self.take().text
            left = Binary(op, left, self.additive())
            if self.peek_op(*COMPARISONS):
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
        if name not in FUNCTIONS:
            raise FormulaError("formula.unknown_function", name=name)
        self.expect("(")
        args: list[Node] = []
        if not self.peek_op(")"):
            args.append(self.comparison())
            while self.peek_op(","):
                self.take()
                args.append(self.comparison())
        self.expect(")")
        lo, hi = FUNCTIONS[name]
        if len(args) < lo or (hi is not None and len(args) > hi):
            raise FormulaError("formula.arity", name=name, count=len(args))
        if name == "lookup" and not isinstance(args[0], Name):
            raise FormulaError("formula.lookup_table_name")
        return Call(name, tuple(args))


_CACHE: dict[str, Node] = {}


def parse(text: str) -> Node:
    """解析失败抛 FormulaError。"""
    node = _CACHE.get(text)
    if node is None:
        node = _Parser(text).parse()
        if len(_CACHE) < 10000:
            _CACHE[text] = node
    return node


def names(node: Node) -> set[str]:
    """公式里引用的全部名字（不含 lookup 的表名）。"""
    match node:
        case Name(name=n):
            return {n}
        case Unary(operand=o):
            return names(o)
        case Binary(left=a, right=b):
            return names(a) | names(b)
        case Call(func=f, args=args):
            out: set[str] = set()
            for a in args[1:] if f == "lookup" else args:
                out |= names(a)
            return out
        case _:
            return set()


def tables(node: Node) -> set[str]:
    """lookup 引用的表名。"""
    match node:
        case Unary(operand=o):
            return tables(o)
        case Binary(left=a, right=b):
            return tables(a) | tables(b)
        case Call(func=f, args=args):
            out: set[str] = set()
            if f == "lookup":
                first = args[0]
                assert isinstance(first, Name)
                out.add(first.name)
                args = args[1:]
            for a in args:
                out |= tables(a)
            return out
        case _:
            return set()


type Resolver = Callable[[str], Value]
type TableLookup = Callable[[str, Value], float]


def _num(v: Value) -> float:
    if isinstance(v, str):
        raise FormulaError("formula.text_in_arithmetic", value=v)
    return v


def _round_half_away(v: float) -> float:
    # 四舍五入（远离零），不用银行家舍入，便于规则书描述
    return float(math.floor(v + 0.5)) if v >= 0 else -float(math.floor(-v + 0.5))


def evaluate(node: Node, resolve: Resolver, lookup: TableLookup) -> Value:
    match node:
        case Num(value=v):
            return v
        case Str(value=s):
            return s
        case Name(name=n):
            return resolve(n)
        case Unary(operand=o):
            return -_num(evaluate(o, resolve, lookup))
        case Binary(op=op, left=a, right=b):
            x = evaluate(a, resolve, lookup)
            y = evaluate(b, resolve, lookup)
            return _binary(op, x, y)
        case Call(func=f, args=args):
            if f == "lookup":
                first = args[0]
                assert isinstance(first, Name)
                return lookup(first.name, evaluate(args[1], resolve, lookup))
            vals = [_num(evaluate(a, resolve, lookup)) for a in args]
            if f == "floor":
                return float(math.floor(vals[0]))
            if f == "ceil":
                return float(math.ceil(vals[0]))
            if f == "round":
                return _round_half_away(vals[0])
            if f == "min":
                return min(vals)
            return max(vals)


def _binary(op: str, x: Value, y: Value) -> Value:
    if op in ("==", "!="):
        eq = x == y
        return 1.0 if (eq if op == "==" else not eq) else 0.0
    fx, fy = _num(x), _num(y)
    if op == "+":
        return fx + fy
    if op == "-":
        return fx - fy
    if op == "*":
        return fx * fy
    if op == "/":
        if fy == 0:
            raise FormulaError("formula.division_by_zero")
        return fx / fy
    result = {"<": fx < fy, "<=": fx <= fy, ">": fx > fy, ">=": fx >= fy}[op]
    return 1.0 if result else 0.0
