"""技能设置：一串赋值，每行 名字 = 值。

    target = "single"            # 文字、True / False、数字
    range = 30 + this.level * 5  # 公式
    cooldown = None              # 不设
    shape = sphere(radius=5)     # 带参数的构造：名字(参数=值, ...)

语法就是 Python 的赋值（用 ast 解析，不执行）；# 是注释，pass 什么都不做。
这里只管语法：每一项的名字、值的写法（公式文本、构造的名字和参数）；有哪些名字、值该是什么，由调用方（rules）决定。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import cast

from smartkeeper.lang.formula import FormulaError, convert, desugar, syntax_error, to_text


@dataclass(frozen=True, slots=True)
class Setting:
    """一项设置。value 是公式文本（None 写成空）；构造时 call 是构造的名字，args 是各参数的公式文本；
    文字列表（["dodge", "block"]）时 items 是这些文字。"""

    line: int
    name: str
    value: str = ""
    call: str | None = None
    args: tuple[tuple[str, str], ...] = ()
    items: tuple[str, ...] | None = None


def _formula(node: ast.expr, line: int) -> str:
    if isinstance(node, ast.Constant) and node.value is None:
        return ""
    try:
        return to_text(convert(node))
    except FormulaError as e:
        raise FormulaError(e.code, **{"line": line, **e.params}) from None


def parse_config(text: str) -> tuple[Setting, ...]:
    """解析失败抛 FormulaError，参数里带 line。同一个名字写两次报 config.duplicate。"""
    src = desugar(text)
    if not src.strip():
        return ()
    try:
        tree = ast.parse(src, mode="exec")
    except SyntaxError as e:
        raise syntax_error(e, src, script=True) from None
    out: list[Setting] = []
    seen: set[str] = set()
    for s in tree.body:
        if isinstance(s, ast.Pass):
            continue
        if not (
            isinstance(s, ast.Assign) and len(s.targets) == 1 and isinstance(s.targets[0], ast.Name)
        ):
            text_ = (ast.get_source_segment(src, s) or "").split("\n")[0]
            raise FormulaError("config.bad_line", line=s.lineno, text=text_)
        name = s.targets[0].id
        if name in seen:
            raise FormulaError("config.duplicate", line=s.lineno, name=name)
        seen.add(name)
        v = s.value
        if isinstance(v, ast.List | ast.Tuple):
            if not all(isinstance(x, ast.Constant) and isinstance(x.value, str) for x in v.elts):
                raise FormulaError("config.list_of_text", line=s.lineno, name=name)
            items = tuple(str(cast(ast.Constant, x).value) for x in v.elts)
            out.append(Setting(line=s.lineno, name=name, items=items))
            continue
        if (
            isinstance(v, ast.Call)
            and isinstance(v.func, ast.Name)
            and v.args
            and not v.keywords
            and all(isinstance(x, ast.Constant) and isinstance(x.value, str) for x in v.args)
        ):
            # 名字("a", "b")：一串文字参数，例如 check = best("strength", "agility")
            items = tuple(str(cast(ast.Constant, x).value) for x in v.args)
            out.append(Setting(line=s.lineno, name=name, call=v.func.id, items=items))
            continue
        if isinstance(v, ast.Call) and isinstance(v.func, ast.Name) and v.keywords:
            if v.args or any(k.arg is None for k in v.keywords):
                raise FormulaError("config.call_keywords", line=s.lineno, name=v.func.id)
            args = tuple((str(k.arg), _formula(k.value, s.lineno)) for k in v.keywords)
            out.append(Setting(line=s.lineno, name=name, call=v.func.id, args=args))
        else:
            out.append(Setting(line=s.lineno, name=name, value=_formula(v, s.lineno)))
    return tuple(out)
