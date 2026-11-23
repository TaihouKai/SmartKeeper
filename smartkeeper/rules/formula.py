"""受限的公式语言。引擎不执行任何外部代码，这里是自己的解析器和求值器。

- 数字、"字符串"、+ - * /、比较（< <= > >= == !=，结果是 1 或 0；单个 = 等同 ==）、括号
- 名字：字段、推导值、命名公式；条目里可用 self.x
- 掷骰：NdM。数字后面紧跟 d 就是掷骰（3d6、1dstr、2d(str+1)）；名字和名字之间要加空格
  （np_level d luck）；d20 等于 1d20，d% 等于 1d100。掷骰比乘除先算：2d6*5 是 (2d6)*5。
- 函数见 FUNCTIONS。

掷骰只在调用方给了 faces（真正产生随机数的函数）时允许；推导值、上下限这类每次都要重算的公式
没有 faces，遇到掷骰就报 formula.dice_not_allowed。
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass

# 函数名 -> (最少参数, 最多参数；None 表示不限)
FUNCTIONS: dict[str, tuple[int, int | None]] = {
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
    "highest": (3, 3),
    "lowest": (3, 3),
}

COMPARISONS = ("<", "<=", ">", ">=", "==", "!=")
MAX_DICE = 1000
MAX_SIDES = 100000

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


@dataclass(frozen=True, slots=True)
class Dice:
    count: Node
    sides: Node


type Node = Num | Str | Name | Unary | Binary | Call | Dice

_TOKEN = re.compile(
    r"\s*(?:(?P<num>\d+(?:\.\d+)?)|(?P<str>\"[^\"]*\")|(?P<name>[^\W\d]\w*(?:\.[^\W\d]\w*)?)"
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


def _children(node: Node) -> tuple[Node, ...]:
    match node:
        case Unary(operand=o):
            return (o,)
        case Binary(left=a, right=b):
            return (a, b)
        case Call(args=args):
            return args
        case Dice(count=c, sides=s):
            return (c, s)
        case _:
            return ()


def names(node: Node) -> set[str]:
    """公式里引用的全部名字（不含 lookup 的表名）。"""
    if isinstance(node, Name):
        return {node.name}
    kids = _children(node)
    if isinstance(node, Call) and node.func == "lookup":
        kids = kids[1:]
    out: set[str] = set()
    for k in kids:
        out |= names(k)
    return out


def tables(node: Node) -> set[str]:
    """lookup 引用的表名。"""
    out: set[str] = set()
    kids = _children(node)
    if isinstance(node, Call) and node.func == "lookup":
        first = kids[0]
        assert isinstance(first, Name)
        out.add(first.name)
        kids = kids[1:]
    for k in kids:
        out |= tables(k)
    return out


def is_die_name(name: str) -> bool:
    """d、d6 这样的名字会被当成掷骰，不能用作字段名。"""
    return _DIE_NAME.fullmatch(name) is not None


def has_dice(node: Node) -> bool:
    if isinstance(node, Dice) or (isinstance(node, Call) and node.func in ("highest", "lowest")):
        return True
    return any(has_dice(k) for k in _children(node))


type Resolver = Callable[[str], Value]
type TableLookup = Callable[[str, Value], float]
type Faces = Callable[[int, int], tuple[int, ...]]  # (个数, 面数) -> 每颗骰子的点数


def _num(v: Value) -> float:
    if isinstance(v, str):
        raise FormulaError("formula.text_in_arithmetic", value=v)
    return v


def truthy(v: Value) -> bool:
    return v != 0 and v != ""


def _round_half_away(v: float) -> float:
    # 四舍五入（远离零），不用银行家舍入，便于规则书描述
    return float(math.floor(v + 0.5)) if v >= 0 else -float(math.floor(-v + 0.5))


def _dice_args(count: float, sides: float) -> tuple[int, int]:
    n, s = int(_round_half_away(count)), int(_round_half_away(sides))
    if not (0 <= n <= MAX_DICE) or not (1 <= s <= MAX_SIDES):
        raise FormulaError("formula.dice_range", count=n, sides=s)
    return n, s


@dataclass(frozen=True, slots=True)
class _Eval:
    resolve: Resolver
    lookup: TableLookup
    faces: Faces | None

    def roll(self, count: float, sides: float) -> tuple[int, ...]:
        if self.faces is None:
            raise FormulaError("formula.dice_not_allowed")
        n, s = _dice_args(count, sides)
        return self.faces(n, s) if n else ()

    def num(self, node: Node) -> float:
        return _num(self.run(node))

    def run(self, node: Node) -> Value:
        match node:
            case Num(value=v):
                return v
            case Str(value=s):
                return s
            case Name(name=n):
                return self.resolve(n)
            case Unary(operand=o):
                return -self.num(o)
            case Binary(op=op, left=a, right=b):
                return _binary(op, self.run(a), self.run(b))
            case Dice(count=c, sides=s):
                return float(sum(self.roll(self.num(c), self.num(s))))
            case Call(func=fn, args=args):
                return self.call(fn, args)

    def call(self, fn: str, args: tuple[Node, ...]) -> Value:
        # 需要惰性求值或特殊参数的函数
        if fn == "lookup":
            first = args[0]
            assert isinstance(first, Name)
            return self.lookup(first.name, self.run(args[1]))
        if fn == "if":
            return self.run(args[1]) if truthy(self.run(args[0])) else self.run(args[2])
        if fn == "and":
            return 1.0 if all(truthy(self.run(a)) for a in args) else 0.0
        if fn == "or":
            return 1.0 if any(truthy(self.run(a)) for a in args) else 0.0
        if fn == "not":
            return 0.0 if truthy(self.run(args[0])) else 1.0
        v = [self.num(a) for a in args]
        if fn in ("highest", "lowest"):
            faces = sorted(self.roll(v[0], v[1]), reverse=fn == "highest")
            k = max(0, int(_round_half_away(v[2])))
            return float(sum(faces[:k]))
        return _math(fn, v)


def _math(fn: str, v: list[float]) -> float:
    x = v[0]
    try:
        match fn:
            case "abs":
                return abs(x)
            case "floor":
                return float(math.floor(x))
            case "ceil":
                return float(math.ceil(x))
            case "round":
                return _round_half_away(x)
            case "trunc":
                return float(math.trunc(x))
            case "sign":
                return (x > 0) - (x < 0) + 0.0
            case "sqrt":
                return math.sqrt(x)
            case "pow":
                r = math.pow(x, v[1])
            case "mod":
                if v[1] == 0:
                    raise FormulaError("formula.division_by_zero")
                return x % v[1]  # 结果和除数同号，例如 mod(-1, 3) = 2
            case "min":
                return min(v)
            case "max":
                return max(v)
            case "clamp":
                return min(max(x, v[1]), v[2])
            case _:
                raise FormulaError("formula.unknown_function", name=fn)
    except (ValueError, OverflowError) as e:
        raise FormulaError("formula.math_domain", name=fn) from e
    if isinstance(r, complex) or math.isinf(r) or math.isnan(r):
        raise FormulaError("formula.math_domain", name=fn)
    return r


def evaluate(
    node: Node, resolve: Resolver, lookup: TableLookup, faces: Faces | None = None
) -> Value:
    return _Eval(resolve, lookup, faces).run(node)


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
