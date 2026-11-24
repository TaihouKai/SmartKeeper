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

- 语法就是 Python：一行一句，也可以用 ; 隔开；括号没关上时可以换行接着写；# 后面是注释；pass 什么都不做。
- 每句是 <对象>.<动作>(参数, ...)。对象：self 是使用者自己，target 是使用时选的对象（也可以是自己）。
- 字段参数写名字；其余参数和条件是公式（见 formula.py）。
- if / elif / else 后面写冒号，下面缩进的几行是这一支（缩进多少都行，同一支里要对齐）；可以套着写。

用 ast 解析（不执行），只认上面这些写法。这里只管语法：解析出语句，参数写成公式文本（formula.to_text），
由调用方在自己的上下文里求值。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Literal

from smartkeeper.lang.formula import FormulaError, convert, desugar, syntax_error, to_text

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


@dataclass(frozen=True, slots=True)
class Let:
    """局部变量：名字 = 公式。后面的句子可以用这个名字；只算一次。"""

    line: int
    name: str
    value: str


type ScriptNode = Statement | If | Let


def _arg(node: ast.expr, line: int) -> str:
    try:
        return to_text(convert(node))
    except FormulaError as e:
        raise FormulaError(e.code, **{"line": line, **e.params}) from None


def _statement(call: ast.Call, line: int, src: str) -> Statement:
    func = call.func
    if not isinstance(func, ast.Attribute) or not isinstance(func.value, ast.Name):
        raise FormulaError(
            "script.bad_statement", line=line, text=ast.get_source_segment(src, call) or ""
        )
    who, verb = func.value.id, func.attr
    if who not in RECEIVERS:
        raise FormulaError("script.unknown_receiver", line=line, name=who)
    if verb not in VERBS:
        raise FormulaError("script.unknown_verb", line=line, name=verb)
    spec = VERBS[verb]
    args = call.args
    need = sum(1 for s in spec if not s.endswith("?"))
    if (
        call.keywords
        or any(isinstance(a, ast.Starred) for a in args)
        or not need <= len(args) <= len(spec)
    ):
        raise FormulaError(
            "script.arity", line=line, name=verb, count=len(args) + len(call.keywords)
        )
    got: dict[str, str] = {}
    for kind, arg in zip(spec, args, strict=False):
        kind = kind.rstrip("?")
        if kind == "field":
            if not isinstance(arg, ast.Name):
                raise FormulaError("script.field_arg", line=line, name=verb)
            got[kind] = arg.id
        else:
            got[kind] = _arg(arg, line)
    return Statement(
        line=line,
        receiver="self" if who == "self" else "target",
        verb=verb,
        field=got.get("field"),
        amount=got.get("amount"),
        formula=got.get("formula"),
        minutes=got.get("minutes"),
    )


def _if(node: ast.If, src: str) -> If:
    branches: list[Branch] = []
    cur = node
    while True:
        cond = _arg(cur.test, cur.lineno)
        branches.append(Branch(line=cur.lineno, condition=cond, body=_body(cur.body, src)))
        rest = cur.orelse
        if len(rest) == 1 and isinstance(rest[0], ast.If):
            cur = rest[0]  # elif（else: 下面只有一个 if 也一样）
            continue
        if rest:
            branches.append(Branch(line=rest[0].lineno, condition=None, body=_body(rest, src)))
        break
    return If(line=node.lineno, branches=tuple(branches))


def _body(stmts: list[ast.stmt], src: str) -> tuple[ScriptNode, ...]:
    out: list[ScriptNode] = []
    for s in stmts:
        if isinstance(s, ast.Pass):
            continue
        if isinstance(s, ast.If):
            out.append(_if(s, src))
        elif (
            isinstance(s, ast.Assign) and len(s.targets) == 1 and isinstance(s.targets[0], ast.Name)
        ):
            name = s.targets[0].id
            if name in (*RECEIVERS, "this"):
                raise FormulaError("script.bad_variable", line=s.lineno, name=name)
            out.append(Let(line=s.lineno, name=name, value=_arg(s.value, s.lineno)))
        elif isinstance(s, ast.Expr) and isinstance(s.value, ast.Call):
            out.append(_statement(s.value, s.lineno, src))
        else:
            text = ast.get_source_segment(src, s) or ""
            raise FormulaError("script.bad_statement", line=s.lineno, text=text.split("\n")[0])
    return tuple(out)


def parse_script(text: str) -> tuple[ScriptNode, ...]:
    """解析失败抛 FormulaError，参数里带 line（第几行）。空脚本是空元组。"""
    src = desugar(text)
    if not src.strip():
        return ()
    try:
        tree = ast.parse(src, mode="exec")
    except SyntaxError as e:
        raise syntax_error(e, src, script=True) from None
    return _body(tree.body, src)


def statements(nodes: tuple[ScriptNode, ...]) -> list[Statement]:
    """所有的动作句，包括各个分支里的。"""
    out: list[Statement] = []
    for n in nodes:
        if isinstance(n, Statement):
            out.append(n)
        elif isinstance(n, If):
            for b in n.branches:
                out += statements(b.body)
    return out
