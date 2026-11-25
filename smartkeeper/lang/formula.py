"""公式语言。语法借用 Python 的表达式（用 ast 解析，不执行），只认白名单里的写法，求值是自己的。

- 数字、"文字"（单双引号都行）、+ - * / // % **、比较（< <= > >= == !=，结果 1 或 0；可以连写 1 < x < 3）、括号
- a if 条件 else b、and、or、not
- 名字：字段、推导值、命名公式；self.x 是自己的（和直接写 x 一样）；条目里 this.x 是这一条的列；
  <模板>.x 引用自己这边（自己，或同一玩家控制的那个模板的角色），
  <模板>.<条目ID> 是有没有这一条（1/0），<模板>.<条目ID>.<列> 是那一条的列；target.x 是作用对象的
- 掷骰：3d6、d20、d%（= d100）、2d(str + 1)、1d str，解析前改写成 dice(个数, 面数)；两个名字之间写 dice(level, luck)。
  掷骰是一个整体：2d6 * 5 是 (2d6) * 5。
- 函数见 FUNCTIONS。

掷骰只在调用方给了 faces（真正产生随机数的函数）时允许；推导值、上下限这类每次都要重算的公式
没有 faces，遇到掷骰就报 formula.dice_not_allowed。
"""

from __future__ import annotations

import ast
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
    "lookup": (2, 2),
    "count": (1, 2),
    "sum": (1, 1),
    "highest": (3, 3),
    "lowest": (3, 3),
    "dice": (2, 2),
    # 有没有这个状态（1/0），例如 has("中毒")；inside("营地") 是“站在自己用这个条目放的设置物里”
    "has": (1, 1),
    "inside": (1, 1),
}
# if / and / or / not 是 Python 的关键字（a if c else b、a and b、not a），解析成内部的同名调用

# 第一个参数是分组引用（分组、分组.列、<模板>.分组.列、target.分组.列），不是普通名字
LIST_FUNCTIONS = ("count", "sum")
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
    name: str  # "x"、"this.x"、"target.x" ……


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

# ---------------- 文本 -> 公式树：借用 Python 的语法（ast），只认白名单里的写法 ----------------

_NUM = re.compile(r"\d+(?:\.\d+)?")
_IDENT = re.compile(r"[^\W\d]\w*")
_DOTTED = re.compile(r"[^\W\d]\w*(?:\.[^\W\d]\w*)*")
_DIE_NAME = re.compile(r"[dD]\d*")


def _skip_string(text: str, i: int) -> int:
    """text[i] 是引号，返回字符串结束后的位置（没关上就到末尾，让 Python 报错）。"""
    q = text[i]
    j = i + 1
    while j < len(text):
        if text[j] == "\\":
            j += 2
            continue
        if text[j] == q or text[j] == "\n":
            return j + 1
        j += 1
    return j


def _group(text: str, i: int) -> int:
    """text[i] 是 (，返回配对的 ) 之后的位置；没配对就是 -1。"""
    depth = 0
    j = i
    while j < len(text):
        c = text[j]
        if c in "\"'":
            j = _skip_string(text, j)
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return -1


def _sides(text: str, i: int, space: bool) -> tuple[str, int] | None:
    """掷骰的面数：%、数字、(…)、名字（可以带调用）。返回 (改写后的文本, 结束位置)。"""
    j = i
    if space:
        while j < len(text) and text[j] in " \t":
            j += 1
    if j >= len(text):
        return None
    c = text[j]
    if c == "%":
        return "100", j + 1
    m = _NUM.match(text, j)
    if m:
        return m.group(), m.end()
    if c == "(":
        end = _group(text, j)
        return None if end < 0 else (f"({desugar(text[j + 1 : end - 1])})", end)
    m = _DOTTED.match(text, j)
    if m:
        end = m.end()
        if end < len(text) and text[end] == "(":
            close = _group(text, end)
            if close < 0:
                return None
            return f"{m.group()}({desugar(text[end + 1 : close - 1])})", close
        return m.group(), end
    return None


def desugar(text: str) -> str:
    """掷骰写法改成函数：3d6 -> dice(3, 6)，d20 -> dice(1, 20)，d% -> dice(1, 100)，
    2d(str + 1)、1d str、1dstr 也一样。字符串和注释里的不动；改写不跨行，行号不变。"""
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c in "\"'":
            j = _skip_string(text, i)
            out.append(text[i:j])
            i = j
            continue
        if c == "#":
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append(text[i:j])
            i = j
            continue
        prev = text[i - 1] if i else ""
        m = _NUM.match(text, i)
        if m and not (prev.isalnum() or prev in ("_", ".")):
            end = m.end()
            if end < n and text[end] in "dD":
                got = _sides(text, end + 1, space=True)
                if got is not None:
                    out.append(f"dice({m.group()}, {got[0]})")
                    i = got[1]
                    continue
            out.append(m.group())
            i = end
            continue
        m = _IDENT.match(text, i)
        if m:
            word = m.group()
            if prev != "." and _DIE_NAME.fullmatch(word):
                got = _sides(text, i + 1, space=False) if len(word) == 1 else (word[1:], m.end())
                if got is not None:
                    out.append(f"dice(1, {got[0]})")
                    i = got[1]
                    continue
            out.append(word)
            i = m.end()
            continue
        out.append(c)
        i += 1
    return "".join(out)


_IF_CALL = re.compile(r"(?<![\w.])(?:el)?if\s*\(")


def _if_call(line: str) -> bool:
    """这一行有没有 if(…, …) 这种把 if 当函数用的写法（括号里第一层有逗号）。"""
    for m in _IF_CALL.finditer(line):
        depth = 0
        for c in line[m.end() - 1 :]:
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    break
            elif c == "," and depth == 1:
                return True
    return False


def syntax_error(e: SyntaxError, src: str, script: bool) -> FormulaError:
    """Python 的语法错误换成我们的代码；script 时带行号。"""
    msg = e.msg or ""
    line = e.lineno or 1
    extra: dict[str, str | int | float] = {"line": line} if script else {}
    if isinstance(e, IndentationError):
        if msg.startswith("expected an indented block"):
            return FormulaError("script.empty_block", line=max(1, line - 1))
        return FormulaError("script.unexpected_indent", line=line)
    lines = src.split("\n")
    at = lines[line - 1] if 0 < line <= len(lines) else ""
    col = (e.offset or 1) - 1
    if _if_call(at):
        # 旧写法 if(条件, a, b)：if 是 Python 的关键字，不能当函数
        return FormulaError("script.if_call" if script else "formula.if_call", **extra)
    if "was never closed" in msg:
        return FormulaError("formula.unclosed", **extra)
    if msg.startswith("unmatched"):
        return FormulaError("formula.unmatched", **extra)
    if msg.startswith("unterminated string"):
        return FormulaError("formula.unclosed_string", **extra)
    if "instead of '='" in msg or (
        0 <= col < len(at) and at[col] == "=" and at[col + 1 : col + 2] != "="
    ):
        return FormulaError("formula.single_equals", **extra)
    return FormulaError("formula.syntax", **extra)


_COMPARE: dict[type, str] = {
    ast.Lt: "<",
    ast.LtE: "<=",
    ast.Gt: ">",
    ast.GtE: ">=",
    ast.Eq: "==",
    ast.NotEq: "!=",
}
_ARITH: dict[type, str] = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/"}


def dotted(n: ast.expr) -> str | None:
    """a、a.b、a.b.c 这样的名字；别的写法返回 None。"""
    parts: list[str] = []
    while isinstance(n, ast.Attribute):
        parts.append(n.attr)
        n = n.value
    if not isinstance(n, ast.Name):
        return None
    parts.append(n.id)
    return ".".join(reversed(parts))


def convert(n: ast.expr) -> Node:
    """Python 的表达式树 -> 公式树。白名单之外的写法报 formula.unsupported。"""
    match n:
        case ast.Constant(value=bool() as b):
            return Num(1.0 if b else 0.0)
        case ast.Constant(value=int() | float() as v):
            return Num(float(v))
        case ast.Constant(value=str() as s):
            return Str(s)
        case ast.Name() | ast.Attribute():
            name = dotted(n)
            if name is None:
                raise FormulaError("formula.unsupported", what=ast.unparse(n))
            return Name(name)
        case ast.UnaryOp(op=ast.USub(), operand=o):
            return Unary("-", convert(o))
        case ast.UnaryOp(op=ast.UAdd(), operand=o):
            return convert(o)
        case ast.UnaryOp(op=ast.Not(), operand=o):
            return Call("not", (convert(o),))
        case ast.BinOp(op=op, left=a, right=b):
            x, y = convert(a), convert(b)
            if type(op) in _ARITH:
                return Binary(_ARITH[type(op)], x, y)
            if isinstance(op, ast.Mod):
                return Call("mod", (x, y))
            if isinstance(op, ast.Pow):
                return Call("pow", (x, y))
            if isinstance(op, ast.FloorDiv):
                return Call("floor", (Binary("/", x, y),))
        case ast.BoolOp(op=op, values=vs):
            return Call("and" if isinstance(op, ast.And) else "or", tuple(convert(v) for v in vs))
        case ast.Compare(left=a, ops=ops, comparators=cs) if all(type(o) in _COMPARE for o in ops):
            items = [convert(a), *(convert(c) for c in cs)]
            parts = tuple(
                Binary(_COMPARE[type(o)], items[k], items[k + 1]) for k, o in enumerate(ops)
            )
            if len(parts) > 1 and any(has_dice(x) for x in items[1:-1]):
                raise FormulaError("formula.chained_comparison")  # 中间那项会掷两次
            return parts[0] if len(parts) == 1 else Call("and", parts)
        case ast.IfExp(test=c, body=a, orelse=b):
            return Call("if", (convert(c), convert(a), convert(b)))
        case ast.Call(func=ast.Name(id=fn), args=args, keywords=[]) if not any(
            isinstance(a, ast.Starred) for a in args
        ):
            return _call(fn, args)
        case ast.Call(func=func):
            raise FormulaError("formula.unknown_function", name=dotted(func) or ast.unparse(func))
        case _:
            pass
    raise FormulaError("formula.unsupported", what=ast.unparse(n))


def _call(name: str, args: list[ast.expr]) -> Node:
    if name not in FUNCTIONS:
        raise FormulaError("formula.unknown_function", name=name)
    lo, hi = FUNCTIONS[name]
    if len(args) < lo or (hi is not None and len(args) > hi):
        raise FormulaError("formula.arity", name=name, count=len(args))
    if name in ("lookup", *LIST_FUNCTIONS):
        ref = dotted(args[0])
        if ref is None:
            raise FormulaError(
                "formula.lookup_table_name" if name == "lookup" else "formula.list_ref", name=name
            )
        return Call(name, (Name(ref), *(convert(a) for a in args[1:])))
    if name == "dice":
        return Dice(convert(args[0]), convert(args[1]))
    return Call(name, tuple(convert(a) for a in args))


_CACHE: dict[str, Node] = {}


def parse(text: str) -> Node:
    """解析失败抛 FormulaError。"""
    node = _CACHE.get(text)
    if node is None:
        src = desugar(text).strip()
        if not src:
            raise FormulaError("formula.empty")
        try:
            tree = ast.parse(src, mode="eval")
        except SyntaxError as e:
            raise syntax_error(e, src, script=False) from None
        node = convert(tree.body)
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
    """公式里引用的全部名字（不含 lookup 的表名和 count/sum 的分组引用）。"""
    if isinstance(node, Name):
        return {node.name}
    kids = _children(node)
    if isinstance(node, Call) and node.func in ("lookup", *LIST_FUNCTIONS):
        kids = kids[1:]
    out: set[str] = set()
    for k in kids:
        out |= names(k)
    return out


def lists(node: Node) -> set[str]:
    """count/sum 的分组引用。"""
    out: set[str] = set()
    kids = _children(node)
    if isinstance(node, Call) and node.func in LIST_FUNCTIONS:
        first = kids[0]
        assert isinstance(first, Name)
        out.add(first.name)
        kids = kids[1:]
    for k in kids:
        out |= lists(k)
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


def substitute(node: Node, fn: Callable[[str], Node | None]) -> Node:
    """把名字换成别的公式树（fn 返回 None 的名字不换）。lookup 的表名和 count/sum 的分组引用不算名字。"""

    def go(n: Node) -> Node:
        match n:
            case Name(name=x):
                hit = fn(x)
                return n if hit is None else hit
            case Unary(op=op, operand=o):
                return Unary(op, go(o))
            case Binary(op=op, left=a, right=b):
                return Binary(op, go(a), go(b))
            case Dice(count=c, sides=s):
                return Dice(go(c), go(s))
            case Call(func=fn_name, args=args):
                keep = 1 if fn_name in ("lookup", *LIST_FUNCTIONS) else 0
                return Call(fn_name, args[:keep] + tuple(go(a) for a in args[keep:]))
            case _:
                return n

    return go(node)


def is_die_name(name: str) -> bool:
    """d、d6 这样的名字会被当成掷骰，不能用作字段名。"""
    return _DIE_NAME.fullmatch(name) is not None


_PREC = {"+": 6, "-": 6, "*": 7, "/": 7, "<": 5, "<=": 5, ">": 5, ">=": 5, "==": 5, "!=": 5}


def to_text(node: Node, values: dict[str, Value] | None = None) -> str:
    """把公式树写回文本（能再被 parse 读回来，只加必要的括号），values 里的名字换成那个值。"""
    vals = values or {}

    def lit(v: Value) -> tuple[str, int]:
        if isinstance(v, str):
            return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"', 10
        text = repr(float(v)) if not float(v).is_integer() else str(int(v))
        return text, 8 if text.startswith("-") else 10

    def whole(n: Node) -> bool:
        return isinstance(n, Num) and n.value >= 0 and float(n.value).is_integer()

    def at(n: Node, need: int) -> str:
        """n 的文本；优先级低于 need 时加括号。"""
        text, p = go(n)
        return f"({text})" if p < need else text

    # 优先级：if-else 1，or 2，and 3，not 4，比较 5，加减 6，乘除 7，取负 8，原子 10
    def go(n: Node) -> tuple[str, int]:
        match n:
            case Num(value=v) | Str(value=v):
                return lit(v)
            case Name(name=x):
                return lit(vals[x]) if x in vals else (x, 10)
            case Unary(operand=o):
                return f"-{at(o, 8)}", 8
            case Binary(op=op, left=a, right=b):
                p = _PREC[op]
                # 比较不能连着写（那是另一种意思），两边都要比它高；其余左结合
                return f"{at(a, p + 1 if p == 5 else p)} {op} {at(b, p + 1)}", p
            case Dice(count=c, sides=sd):
                if whole(c) and whole(sd):
                    return f"{go(c)[0]}d{go(sd)[0]}", 10
                return f"dice({go(c)[0]}, {go(sd)[0]})", 10
            case Call(func="if", args=(c, a, b)):
                return f"{at(a, 2)} if {at(c, 2)} else {at(b, 1)}", 1
            case Call(func="and" | "or" as fn, args=args):
                p = 3 if fn == "and" else 2
                return f" {fn} ".join(at(a, p + 1) for a in args), p
            case Call(func="not", args=(a,)):
                return f"not {at(a, 4)}", 4
            case Call(func=fn, args=args):
                return f"{fn}({', '.join(go(a)[0] for a in args)})", 10

    return go(node)[0]


def has_dice(node: Node) -> bool:
    if isinstance(node, Dice) or (isinstance(node, Call) and node.func in ("highest", "lowest")):
        return True
    return any(has_dice(k) for k in _children(node))


type Resolver = Callable[[str], Value]
type TableLookup = Callable[[str, Value], float]
type Collect = Callable[[str], list[Value]]  # 分组引用 -> 每个条目的值
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
    collect: Collect | None = None

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
        if fn in LIST_FUNCTIONS:
            first = args[0]
            assert isinstance(first, Name)
            if self.collect is None:
                raise FormulaError("formula.list_ref", name=fn)
            items = self.collect(first.name)
            if fn == "sum":
                return float(sum(_num(x) for x in items))
            if len(args) == 1:
                return float(len(items))
            want = self.run(args[1])
            return float(sum(1 for x in items if _same(x, want)))
        if fn in ("has", "inside"):
            tag = self.run(args[0])
            if not isinstance(tag, str):
                raise FormulaError("formula.text_arg", name=fn)
            # 状态由调用方按名字解析：has:<状态名>（inside 是 in:<条目名> 这个状态）
            return self.resolve(f"has:{'in:' if fn == 'inside' else ''}{tag}")
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
    node: Node,
    resolve: Resolver,
    lookup: TableLookup,
    faces: Faces | None = None,
    collect: Collect | None = None,
) -> Value:
    return _Eval(resolve, lookup, faces, collect).run(node)


def _same(x: Value, y: Value) -> bool:
    if isinstance(x, str) or isinstance(y, str):
        return str(x) == str(y)
    return abs(x - y) < 1e-9


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
