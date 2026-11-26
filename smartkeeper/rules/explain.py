"""把条目的技能设置、生效时的脚本、常驻加成写成人读得懂的句子（导出 PDF 等给人看的地方用）。

完全由代码转换，不调用模型：名字换成规则包里的显示名（this.mp_spent → 投入魔力，target.hp → 对象的生命值），
运算写成数学记号，局部变量代回去。连接的字句（“射程 {x} 米”“如果……”）全部来自调用方传进来的 words
（界面翻译表里 ex.* 的那些），所以这里不写死任何一种语言。转换不了的部分原样跳过，不报错。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from smartkeeper import lang as f
from smartkeeper.contracts import Effect, EntityTemplate, ExplainLine, ParamDef, RulePack
from smartkeeper.rules import checkconfig, skillconfig

# 用技能时引擎给的数
ENGINE_VARS = (*skillconfig.SCRIPT_VARS, "time", "day")
_PREC = {"or": 1, "and": 2, "not": 3, "cmp": 4, "+": 5, "-": 5, "*": 6, "/": 6, "//": 6, "%": 6}
_CMP = {">=": "≥", "<=": "≤", ">": ">", "<": "<", "==": "=", "!=": "≠"}
_ARITH = {"+": " + ", "-": " - ", "*": " × ", "/": " ÷ ", "//": " ÷ ", "%": " mod "}


def _num(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:.2f}".rstrip("0").rstrip(".")


class Explainer:
    def __init__(
        self,
        pack: RulePack,
        tpl: EntityTemplate,
        group: str,
        params: Sequence[ParamDef],
        words: Mapping[str, str],
    ) -> None:
        self.pack = pack
        self.tpl = tpl
        self.group = next((g for g in tpl.groups if g.name == group), None)
        self.params = {p.name: p.label or p.name for p in params}
        self.param_defs = {p.name: p for p in params}
        self.words = words
        self.local: dict[str, f.Node] = {}

    # ---------------- 字句 ----------------

    def w(self, key: str, **params: str) -> str:
        text = self.words.get(f"ex.{key}", key)
        for k, v in params.items():
            text = text.replace("{" + k + "}", v)
        return text

    def who(self, receiver: str) -> str:
        if receiver == "self":
            return self.w("self")
        if receiver == "target":
            return self.w("target")
        other = self.pack.template(receiver)
        return other.label or other.name if other else receiver

    def field_label(self, name: str, tpl: EntityTemplate | None = None) -> str:
        for t in [tpl or self.tpl, *self.pack.templates]:
            for x in (*t.fields, *t.derived):
                if x.name == name:
                    return x.label or x.name
        return name

    def column_label(self, name: str) -> str:
        if name in self.params:
            return self.params[name]
        for p in self.pack.params:
            if p.name == name and (not p.groups or (self.group and self.group.name in p.groups)):
                return p.label or p.name
        for c in self.group.fields if self.group else ():
            if c.name == name:
                return c.label or c.name
        return name

    def entry_label(self, tpl: EntityTemplate | None, ref: str) -> str:
        for g in tpl.groups if tpl else ():
            for p in g.presets:
                if ref in (p.id, p.name):
                    return p.name
        return ref

    def name(self, dotted: str) -> str:
        parts = dotted.split(".")
        if dotted in ENGINE_VARS:
            return self.w(f"v.{dotted}")
        if parts[0] == "this" and len(parts) == 2:
            return self.w("this_of", what=self.column_label(parts[1]))
        if parts[0] in ("self", "target") or self.pack.template(parts[0]) is not None:
            if len(parts) == 1:
                return self.who(parts[0])
            other = self.pack.template(parts[0])
            owner = self.tpl if parts[0] == "self" else other
            rest = parts[1:]
            if len(rest) == 1:
                what = self.field_label(rest[0], owner)
            else:  # 同伴（或自己）的某一条的某一列
                what = self.w(
                    "entry_col",
                    entry=self.entry_label(owner, rest[0]),
                    col=self.field_label(rest[-1], owner),
                )
            return what if parts[0] == "self" else self.w("of", who=self.who(parts[0]), what=what)
        if len(parts) == 1:
            return self.params.get(dotted) or self.field_label(dotted)
        return self.w("entry_col", entry=self.entry_label(self.tpl, parts[0]), col=parts[-1])

    # ---------------- 公式 ----------------

    def formula(self, text: str) -> str:
        try:
            node = f.parse(text)
        except f.FormulaError:
            return text
        return self.node(self._inline(node))[0]

    def _inline(self, node: f.Node) -> f.Node:
        return f.substitute(node, lambda x: self.local.get(x)) if self.local else node

    def _wrap(self, part: tuple[str, int], prec: int) -> str:
        text, p = part
        return f"({text})" if p < prec else text

    def _die(self, n: f.Node) -> str:
        """骰子的个数和面数：不是一个数或一个名字时加括号，免得和 d 粘在一起看不清。"""
        text = self.node(n)[0]
        return text if isinstance(n, f.Num | f.Name) else f"({text})"

    def _template_cmp(self, a: f.Node, b: f.Node, op: str) -> str | None:
        """对象.template == "某模板" → 对象是某模板"""
        if isinstance(a, f.Name) and isinstance(b, f.Str) and a.name.endswith("template"):
            owner = a.name.rsplit(".", 1)[0] if "." in a.name else "self"
            other = self.pack.template(b.value)
            label = other.label or other.name if other else b.value
            key = "is" if op == "==" else "is_not"
            return self.w(key, who=self.who(owner), what=label)
        return None

    def node(self, n: f.Node) -> tuple[str, int]:
        match n:
            case f.Num(value=v):
                return _num(v), 9
            case f.Str(value=s):
                return f"「{s}」", 9
            case f.Name(name=x):
                return self.name(x), 9
            case f.Dice(count=c, sides=s):
                return f"{self._die(c)}d{self._die(s)}", 8
            case f.Unary(op=op, operand=o):
                inner = self._wrap(self.node(o), 7)
                return (f"-{inner}" if op == "-" else inner), 7
            case f.Binary(op=op, left=a, right=b) if op in _CMP:
                special = self._template_cmp(a, b, op)
                if special is not None:
                    return special, _PREC["cmp"]
                if isinstance(b, f.Str) or isinstance(a, f.Str):
                    key = "is" if op == "==" else "is_not"
                    left, right = self.node(a)[0], self.node(b)[0]
                    return self.w(key, who=left, what=right), _PREC["cmp"]
                p = _PREC["cmp"]
                return (
                    f"{self._wrap(self.node(a), p + 1)} {_CMP[op]} {self._wrap(self.node(b), p + 1)}",
                    p,
                )
            case f.Binary(op=op, left=a, right=b):
                p = _PREC.get(op, 5)
                sym = _ARITH.get(op, f" {op} ")
                return f"{self._wrap(self.node(a), p)}{sym}{self._wrap(self.node(b), p + 1)}", p
            case f.Call(func=fn, args=args):
                return self.call(fn, args)
        return "?", 9

    def call(self, fn: str, args: tuple[f.Node, ...]) -> tuple[str, int]:
        say = [self.node(a)[0] for a in args]
        if fn == "and":
            p = _PREC["and"]
            return self.w("and").join(self._wrap(self.node(a), p + 1) for a in args), p
        if fn == "or":
            p = _PREC["or"]
            return self.w("or").join(self._wrap(self.node(a), p + 1) for a in args), p
        if fn == "not" and args:
            return self.w("not", x=self._wrap(self.node(args[0]), 4)), _PREC["not"]
        if fn == "if" and len(args) == 3:
            return self.w("if_expr", c=say[0], a=say[1], b=say[2]), 0
        if fn == "dice" and len(args) == 2:
            return f"{self._die(args[0])}d{self._die(args[1])}", 8
        if fn == "lookup" and len(args) == 2:
            table = args[0].value if isinstance(args[0], f.Str) else say[0]
            return self.w("fn.lookup", table=str(table), x=say[1]), 9
        if fn in ("has", "inside", "toggled") and args:
            raw = args[0].value if isinstance(args[0], f.Str) else say[0]
            return self.w(f"fn.{fn}", x=str(raw)), 9
        # 一串式子作参数时加括号，免得“……（向下取整）”“……中较大的”看不出管到哪
        grouped = [
            x if isinstance(a, f.Num | f.Name) or " " not in x else f"({x})"
            for a, x in zip(args, say, strict=True)
        ]
        if fn in ("min", "max"):
            return self.w(f"fn.{fn}", x=self.w("list_sep").join(grouped)), 9
        if fn in ("floor", "ceil", "round", "abs", "sqrt", "trunc", "sign") and len(say) == 1:
            return self.w(f"fn.{fn}", x=grouped[0]), 9
        if fn in ("pow", "mod") and len(say) == 2:
            return self.w(f"fn.{fn}", a=say[0], b=say[1]), 9
        if fn == "clamp" and len(say) == 3:
            return self.w("fn.clamp", x=say[0], lo=say[1], hi=say[2]), 9
        return f"{fn}({', '.join(say)})", 9

    # ---------------- 技能设置 ----------------

    def check_name(self, name: str) -> str:
        cdef = self.pack.check(name)
        if cdef is not None:
            try:
                label = checkconfig.read_check(cdef.config).label
            except f.FormulaError:
                label = ""
            return label or name
        return name

    def config(self, text: str, script: str) -> list[str]:
        try:
            settings = f.parse_config(text)
        except f.FormulaError:
            return []
        # 设置的各项可以互相引用（noise = range / 10）：代回去
        try:
            env = {
                k: v for k, v in skillconfig.names(text, script).items() if k in skillconfig.KEYS
            }
        except f.FormulaError:
            env = {}
        saved = dict(self.local)
        for k, v in env.items():
            self.local.setdefault(k, v)
        out: list[str] = []
        for s in settings:
            line = self.setting(s)
            if line:
                out.append(line)
        self.local = saved
        return out

    def setting(self, s: f.Setting) -> str | None:
        v = s.value.strip()
        k = s.name
        if k == "target":
            kind = v.strip("\"'")
            return None if kind in ("", "single") else self.w(f"c.target_{kind}")
        if k not in skillconfig.KEYS:  # 写定的参数：可选值有名字的写名字（解放真名固定为 不解放）
            if not v:
                return None
            p = self.param_defs.get(k)
            shown = self.choice_name(p.choices, v) if p else None
            return self.w("c.fixed", name=self.column_label(k), x=shown or self.formula(v))
        if k in ("visible", "guard"):
            return self.w(f"c.{k}") if v not in ("", "0", "False") else None
        if k == "check":
            if s.items:
                names = self.w("list_sep").join(self.check_name(x) for x in s.items)
                return self.w("c.check_best", x=names)
            name = v.strip("\"'")
            return self.w("c.check", x=self.check_name(name)) if name and v not in ("1",) else None
        if k == "save":
            name = v.strip("\"'")
            return self.w("c.save", x=self.check_name(name)) if name else None
        if k == "reactions":
            if s.items:
                return self.w(
                    "c.reactions", x=self.w("list_sep").join(self.reaction(x) for x in s.items)
                )
            return self.w("c.reactions_any") if v == "1" else None
        if k == "affects":
            kind = v.strip("\"'")
            return None if kind in ("", "all") else self.w(f"c.affects_{kind}")
        if k in ("shape", "aura", "placement") and s.call:
            args = {name: self.formula(x) for name, x in s.args}
            if k == "placement":
                base = self.w("c.placement" if "radius" in args else "c.placement_any")
            else:
                base = self.w(f"c.{k}_{s.call}")
            for name, x in args.items():
                base = base.replace("{" + name + "}", x)
            extras = [
                self.w(f"c.placement_{name}", x=x)
                for name, x in args.items()
                if k == "placement" and name != "radius"
            ]
            return self.w("list_sep").join([base, *extras])
        if not v:
            return None
        return self.w(f"c.{k}", x=self.formula(v))

    @staticmethod
    def choice_name(choices: Sequence[str], value: str) -> str | None:
        try:
            v = float(value)
        except ValueError:
            return None
        for c in choices:
            name, sep, num = c.partition("=")
            try:
                if sep and abs(float(num) - v) < 1e-9:
                    return name.strip()
            except ValueError:
                continue
        return None

    def param(self, p: ParamDef) -> str:
        """参数和它能取的值：解放真名（不解放／解放）、投入魔力（1～魔力值上限）。"""
        label = p.label or p.name
        if p.choices:
            vals = [
                c.partition("=")[0].strip() if "=" in c else c.replace("~", "～") for c in p.choices
            ]
            return self.w("param", name=label, x=self.w("choice_sep").join(vals))
        if p.min or p.max:
            lo = self.formula(p.min) if p.min else ""
            hi = self.formula(p.max) if p.max else ""
            return self.w("param", name=label, x=self.w("range", lo=lo, hi=hi))
        return label

    def reaction(self, name: str) -> str:
        if self.pack.check(name) is not None:
            return self.check_name(name)
        for g in self.tpl.groups:
            for p in g.presets:
                if name in (p.id, p.name):
                    return p.name
        return name

    # ---------------- 脚本 ----------------

    def script(self, text: str, depth: int = 0) -> list[ExplainLine]:
        try:
            nodes = f.parse_script(text)
        except f.FormulaError:
            return []
        return self._nodes(nodes, depth)

    def _nodes(self, nodes: Sequence[f.ScriptNode], depth: int) -> list[ExplainLine]:
        out: list[ExplainLine] = []
        for n in nodes:
            if isinstance(n, f.Let):
                try:
                    self.local[n.name] = self._inline(f.parse(n.value))
                except f.FormulaError:
                    continue
            elif isinstance(n, f.If):
                for i, b in enumerate(n.branches):
                    if b.condition is None:
                        head = self.w("s.else")
                    else:
                        head = self.w("s.if" if i == 0 else "s.elif", c=self.formula(b.condition))
                    out.append(ExplainLine(depth=depth, text=head))
                    out += self._nodes(b.body, depth + 1)
            else:
                line = self.statement(n)
                if line:
                    out.append(ExplainLine(depth=depth, text=line))
        return out

    def statement(self, st: f.Statement) -> str | None:
        who = self.who(st.receiver)
        text: str | None = None
        if st.verb == "damage" and st.amount:
            text = self.w("s.damage", who=who, x=self.formula(st.amount))
        elif st.verb == "change" and st.field and st.amount is not None and st.op:
            text = self.change(st.receiver, st.field, st.op, st.amount)
        elif st.verb in ("add", "sub", "set") and st.field and st.amount is not None:
            op = {"add": "+=", "sub": "-=", "set": "="}[st.verb]
            text = self.change(st.receiver, st.field, op, st.amount)
        elif st.verb == "modify" and st.field and st.formula:
            text = self.w(
                "s.set", what=self.target_field(st.receiver, st.field), x=self.formula(st.formula)
            )
        elif st.verb == "negate":
            text = self.w("s.negate")
        elif st.verb == "summon" and st.template:
            other = self.pack.template(st.template)
            text = self.w(
                "s.summon",
                n=self.formula(st.count or "1"),
                what=other.label or other.name if other else st.template,
            )
        elif st.verb == "teleport" and st.to:
            text = self.w("s.teleport", who=who, to=self.who(st.to))
        elif st.verb == "locate":
            text = self.w("s.locate", who=who)
        if text and st.minutes:
            text += self.w("s.minutes", x=self.formula(st.minutes))
        return text

    def target_field(self, receiver: str, field: str) -> str:
        if field.startswith("this."):
            return self.w("this_of", what=self.column_label(field[5:]))
        owner = self.tpl if receiver == "self" else self.pack.template(receiver)
        label = self.field_label(field, owner)
        return label if receiver == "self" else self.w("of", who=self.who(receiver), what=label)

    def change(self, receiver: str, field: str, op: str, amount: str) -> str:
        what = self.target_field(receiver, field)
        x = self.formula(amount)
        key = {"+=": "s.add", "-=": "s.sub", "=": "s.set", "*=": "s.mul", "/=": "s.div"}.get(
            op, "s.set"
        )
        return self.w(key, what=what, x=x)

    # ---------------- 常驻加成 ----------------

    def bonus(self, effects: Sequence[Effect]) -> list[str]:
        out: list[str] = []
        for b in effects:
            if b.target and b.formula:
                out.append(self.w("b.line", what=self.name(b.target), x=self.formula(b.formula)))
            elif b.description:
                out.append(b.description)
        return out


def explain(
    pack: RulePack,
    tpl: EntityTemplate,
    group: str,
    config: str,
    script: str,
    effects: Sequence[Effect],
    params: Sequence[ParamDef],
    words: Mapping[str, str],
) -> list[ExplainLine]:
    """一个条目（或物品的一种用途）的设置、脚本、常驻加成，写成一行行句子（depth 是缩进层级）。"""
    # 这一条实际有的参数：规则包给这个分组的默认参数 + 条目自己加的（同名的后者覆盖前者）
    merged: dict[str, ParamDef] = {
        p.name: p for p in pack.params if not p.groups or group in p.groups
    }
    merged |= {p.name: p for p in params}
    ex = Explainer(pack, tpl, group, list(merged.values()), words)
    out = [ExplainLine(depth=0, text=x) for x in ex.config(config, script)]
    # 设置里写定了的参数不用再选
    try:
        fixed = {s.name for s in f.parse_config(config) if s.name not in skillconfig.KEYS}
    except f.FormulaError:
        fixed = set[str]()
    free = [p for p in merged.values() if p.name not in fixed]
    sep = ex.w("list_sep")
    chosen = [ex.param(p) for p in free if not p.by_kp]
    if chosen:
        out.append(ExplainLine(depth=0, text=ex.w("params", x=sep.join(chosen))))
    by_kp = [ex.param(p) for p in free if p.by_kp]
    if by_kp:
        out.append(ExplainLine(depth=0, text=ex.w("params_kp", x=sep.join(by_kp))))
    ex.local = {}
    out += ex.script(script)
    out += [ExplainLine(depth=0, text=x) for x in ex.bonus(effects)]
    return out
