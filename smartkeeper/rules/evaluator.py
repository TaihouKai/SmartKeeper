"""在一张角色卡上求值公式与推导值。纯函数：同一张卡加同一个规则包，结果永远相同。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from pydantic import JsonValue

from smartkeeper import lang as f
from smartkeeper.contracts import (
    USE_SEP,
    DerivedValue,
    Effect,
    EntityTemplate,
    FieldDef,
    GroupDef,
    GroupEntry,
    GroupPreset,
    RulePack,
    Sheet,
)


def open_columns(g: GroupDef, p: GroupPreset) -> list[FieldDef]:
    """固定条目里规则包没写、要玩家建角时填的列（“使用时填写”的列和运行中会变的列不算）。"""
    return [x for x in g.fields if x.cls != "runtime" and x.name not in p.fields]


def table_lookup(pack: RulePack) -> f.TableLookup:
    by_name = {t.name: t for t in pack.tables}

    def lookup(name: str, key: f.Value) -> float:
        table = by_name.get(name)
        if table is None:
            raise f.FormulaError("formula.unknown_table", name=name)
        if table.kind == "exact":
            for k, v in table.rows:
                if k == key:
                    return v
            raise f.FormulaError("formula.lookup_miss", table=name, key=str(key))
        if isinstance(key, str):
            raise f.FormulaError("formula.text_in_arithmetic", value=key)
        best: float | None = None
        best_k = float("-inf")
        for k, v in table.rows:
            if isinstance(k, str):
                continue
            if best_k <= k <= key:
                best, best_k = v, k
        if best is None:
            raise f.FormulaError("formula.lookup_miss", table=name, key=str(key))
        return best

    return lookup


def as_value(v: JsonValue) -> f.Value | None:
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, int | float):
        return float(v)
    if isinstance(v, str):
        return v
    return None


@dataclass
class EntityContext:
    """一个实体的求值上下文。"""

    pack: RulePack
    template: EntityTemplate
    sheet: Sheet
    extra: Mapping[str, f.Value] = field(default_factory=dict[str, f.Value])
    # 同一个玩家控制的其他实体（模板名 -> 角色卡；None 表示有不止一个，引用会报错），和作用对象
    peers: Mapping[str, JsonValue | None] = field(default_factory=dict[str, JsonValue | None])
    target: EntityContext | None = None
    _cache: dict[str, DerivedValue] = field(default_factory=dict[str, DerivedValue])
    # 互相引用的几个实体共用一个栈，跨实体的循环引用也能发现
    _stack: list[str] = field(default_factory=list[str])

    def __post_init__(self) -> None:
        self._peer_ctx: dict[str, EntityContext] = {}
        self._lookup = table_lookup(self.pack)
        self._derived = {d.name: d for d in self.template.derived}
        self._formulas = {x.name: x for x in self.pack.formulas}
        self._fields = {x.name: x for x in self.template.fields}
        self._groups: dict[str, tuple[GroupEntry, ...]] | None = None
        # 掷骰公式列：this.<这种列> 展开成那一列里写的公式
        self._formula_cols = {
            x.name for g in self.template.groups for x in g.fields if x.kind == "formula"
        }

    # ---- 条目：玩家写的加上生效的固定条目 ----

    def active_presets(self) -> dict[str, tuple[GroupEntry, ...]]:
        """条件为真的固定条目。条件只看字段，求值出错（例如字段还没填）当作不生效。"""
        out: dict[str, tuple[GroupEntry, ...]] = {}
        for g in self.template.groups:
            hits: list[GroupEntry] = []
            for p in g.presets:
                if p.when.strip():
                    try:
                        if not f.truthy(self.eval(p.when)):
                            continue
                    except f.FormulaError:
                        continue
                filled = self.sheet.preset_fields.get(g.name, {}).get(p.name, {})
                cols = {x.name for x in open_columns(g, p)} | {
                    x.name for x in g.fields if x.cls == "runtime"
                }
                merged = {k: v for k, v in filled.items() if k in cols} | dict(p.fields)
                data = p.model_dump(exclude={"when"}) | {"fields": merged}
                hits.append(GroupEntry.model_validate(data))
            if hits:
                out[g.name] = tuple(hits)
        return out

    def groups(self) -> dict[str, tuple[GroupEntry, ...]]:
        """全部条目：生效的固定条目在前。运行中会变的列没存值时补上初值，带限时修正的列按修正后的值。"""
        if self._groups is None:
            merged = dict(self.sheet.groups)
            guard = f"{self.template.name}:presets"
            for name, presets in self._guarded(guard, self.active_presets).items():
                merged[name] = presets + merged.get(name, ())
            self._groups = merged  # 先放上，算初值和修正时引用别的条目不会绕回来
            self._groups = {
                g: tuple(self._live_entry(g, e) for e in entries) for g, entries in merged.items()
            }
        return self._groups

    def _live_entry(self, group: str, e: GroupEntry) -> GroupEntry:
        gdef = next((g for g in self.template.groups if g.name == group), None)
        fields = dict(e.fields)
        for fd in gdef.fields if gdef else ():
            if fd.name in fields:
                continue
            if fd.cls == "runtime" and fd.kind == "boolean" and not fd.initial:
                fields[fd.name] = False  # 是/否没写初值：否
            if fd.initial:  # 运行中的列的初值，或者玩家没填的列的默认值
                try:
                    v = self.eval(fd.initial, fields)
                except f.FormulaError:
                    continue
                fields[fd.name] = (v != 0 and v != "") if fd.kind == "boolean" else v
        # 限时修正 <条目名>.<列>（例如“+”让这个技能的等级 10 分钟内变高）
        for st in self.sheet.statuses:
            eff = st.modifier
            if eff is None or not eff.is_mechanical or eff.target is None:
                continue
            head, _, col = eff.target.rpartition(".")
            if head != e.name or not col:
                continue
            cur = as_value(fields.get(col))
            if cur is None or isinstance(cur, str):
                continue
            assert eff.formula is not None
            try:
                fields[col] = self.eval_num(eff.formula, fields, overrides={f"this.{col}": cur})
            except f.FormulaError:
                continue
        return e if fields == e.fields else e.model_copy(update={"fields": fields})

    def full_sheet(self) -> Sheet:
        """给人和 KP 看的完整角色卡：固定条目排在玩家写的条目前面。"""
        return self.sheet.model_copy(update={"groups": self.groups()})

    # ---- 名字解析 ----

    def resolver(
        self,
        entry: Mapping[str, JsonValue] | None = None,
        overrides: Mapping[str, f.Value] | None = None,
    ) -> f.Resolver:
        def resolve(name: str) -> f.Value:
            if overrides is not None and name in overrides:
                return overrides[name]
            if name.startswith("has:"):
                tag = name[4:]
                return 1.0 if any(st.tag == tag for st in self.sheet.statuses) else 0.0
            if name.startswith("toggled:"):
                return float(self.toggled_count(name[8:]))
            if name.startswith("this."):
                if entry is None:
                    raise f.FormulaError("formula.this_outside_entry", name=name)
                key = name[5:]
                if key not in entry:
                    raise f.FormulaError("formula.unknown_name", name=name)
                v = as_value(entry[key])
                if v is None:
                    raise f.FormulaError("formula.bad_value", name=name)
                return v
            if name.startswith("self."):
                return self.member(name[5:].split("."), name)
            if "." in name:
                return self.dotted(name)
            return self.value_of(name)

        return resolve

    # ---- 引用别的实体和条目 ----

    def peer(self, template: str) -> EntityContext | None:
        """同一个玩家控制的那个模板的实体。没有就是 None；有不止一个时报错。"""
        if template not in self.peers:
            return None
        hit = self._peer_ctx.get(template)
        if hit is not None:
            return hit
        raw = self.peers[template]
        tpl = self.pack.template(template)
        if raw is None or tpl is None:
            raise f.FormulaError("formula.ambiguous_partner", name=template)
        mine = self.sheet.model_dump(mode="json")
        theirs: dict[str, JsonValue | None] = {k: v for k, v in self.peers.items() if k != template}
        theirs[self.template.name] = mine
        hit = EntityContext(
            self.pack, tpl, Sheet.model_validate(raw), peers=theirs, _stack=self._stack
        )
        hit._peer_ctx[self.template.name] = self
        self._peer_ctx[template] = hit
        return hit

    def entry_by_id(self, entry_id: str) -> GroupEntry | None:
        for entries in self.groups().values():
            for e in entries:
                if e.id and e.id == entry_id:
                    return e
        return None

    def dotted(self, name: str) -> f.Value:
        """<模板>.x、target.x：自己这边的实体、作用对象的字段、推导值和条目（self.x 见 resolver）。"""
        head, *rest = name.split(".")
        if head == "target":
            if self.target is None:
                raise f.FormulaError("formula.no_target", name=name)
            return self.target.member(rest, name)
        if head == self.template.name:
            return self.member(rest, name)
        other = self.peer(head)
        if other is not None:
            return other.member(rest, name)
        if self.pack.template(head) is not None:
            return 0.0  # 我这边没有这种角色：按 0 算（例如还没有这种同伴）
        raise f.FormulaError("formula.unknown_name", name=name)

    def collect(self, ref: str) -> list[f.Value]:
        """count/sum 的分组引用：分组 / 分组.列，前面可以加 <模板>. 或 target.。

        分组.列 是每个条目这一列的值（没填的跳过）；只写分组是每个条目算一个 1。"""
        head, *rest = ref.split(".")
        ctx: EntityContext | None = self
        if head == "target":
            if self.target is None:
                raise f.FormulaError("formula.no_target", name=ref)
            ctx = self.target
        elif head == self.template.name:
            pass
        elif self.pack.template(head) is not None:
            ctx = self.peer(head)
        else:
            rest = [head, *rest]
        if ctx is None or not rest:
            return []
        if len(rest) > 2 or not any(g.name == rest[0] for g in ctx.template.groups):
            raise f.FormulaError("formula.unknown_group", name=ref)
        entries = ctx.groups().get(rest[0], ())
        if len(rest) == 1:
            return [1.0 for _ in entries]
        out: list[f.Value] = []
        for e in entries:
            v = as_value(e.fields.get(rest[1]))
            if v is not None:
                out.append(v)
        return out

    def member(self, rest: list[str], full: str) -> f.Value:
        if rest == ["template"]:
            return self.template.name
        if len(rest) == 1:
            key = rest[0]
            fd = self._fields.get(key)
            if (
                key in self.extra
                or key in self._derived
                or key in self.sheet.fields
                or key in self._formulas
                or (fd is not None and fd.cls == "player" and fd.initial)
            ):
                return self.value_of(key)
            if any(x.name == key for x in self.template.fields):
                raise f.FormulaError("formula.bad_value", name=full)  # 字段还没填
            return 1.0 if self.entry_by_id(key) is not None else 0.0
        if len(rest) == 2:
            entry = self.entry_by_id(rest[0])
            if entry is None:
                return 0.0
            v = as_value(entry.fields.get(rest[1]))
            return 0.0 if v is None else v
        raise f.FormulaError("formula.unknown_name", name=full)

    def value_of(self, name: str) -> f.Value:
        if name in self.extra:
            return self.extra[name]
        if name in self._derived:
            return self.derived(name).value
        fd = self._fields.get(name)
        if name not in self.sheet.fields and fd is not None and fd.cls == "player" and fd.initial:
            # 玩家没填、有默认值（initial）的字段
            text = fd.initial
            v = self._guarded(f"{self.template.name}.{name}", lambda: self.eval(text))
            return (1.0 if v not in (0, "") else 0.0) if fd.kind == "boolean" else v
        if name in self.sheet.fields:
            v = as_value(self.sheet.fields[name])
            if v is None:
                raise f.FormulaError("formula.bad_value", name=name)
            fd = self._fields.get(name)
            if (
                isinstance(v, str)
                or fd is None
                or fd.cls != "player"
                or f"{self.template.name}:presets" in self._stack
            ):
                return v  # 只修正建角时填的数值；判断固定条目生不生效时用填的原值
            return self.field_value(name, v).value
        if name in self._formulas:
            key = f"{self.template.name}.{name}"
            return self._guarded(key, lambda: self.eval(self._formulas[name].formula))
        raise f.FormulaError("formula.unknown_name", name=name)

    def prepare(self, text: str, entry: Mapping[str, JsonValue] | None = None) -> f.Node:
        """解析公式，并把 this.<掷骰公式列> 换成那一列里写的公式（可以层层引用，成环报错）。"""
        node = f.parse(text)
        if entry is None:
            return node

        def expand(n: f.Node, seen: tuple[str, ...]) -> f.Node:
            def fn(name: str) -> f.Node | None:
                key = name[5:] if name.startswith("this.") else ""
                v = entry.get(key) if key in self._formula_cols else None
                if not isinstance(v, str) or not v.strip():
                    return None
                if key in seen:
                    raise f.FormulaError("formula.cycle", name=" -> ".join([*seen, key]))
                return expand(f.parse(v), (*seen, key))

            return f.substitute(n, fn)

        return expand(node, ())

    def eval(
        self,
        text: str,
        entry: Mapping[str, JsonValue] | None = None,
        faces: f.Faces | None = None,
        overrides: Mapping[str, f.Value] | None = None,
    ) -> f.Value:
        return f.evaluate(
            self.prepare(text, entry),
            self.resolver(entry, overrides),
            self._lookup,
            faces,
            self.collect,
        )

    def eval_num(
        self,
        text: str,
        entry: Mapping[str, JsonValue] | None = None,
        overrides: Mapping[str, f.Value] | None = None,
    ) -> float:
        v = self.eval(text, entry, overrides=overrides)
        if isinstance(v, str):
            raise f.FormulaError("formula.text_result", value=v)
        return v

    def _guarded[T](self, name: str, fn: Callable[[], T]) -> T:
        if name in self._stack:
            raise f.FormulaError("formula.cycle", name=" -> ".join([*self._stack, name]))
        self._stack.append(name)
        try:
            return fn()
        finally:
            self._stack.pop()

    # ---- 推导值 ----

    def is_on(self, entry: str, use: str, default_on: bool) -> bool:
        """开关类用途现在开着没有（没有记录的按默认）。"""
        return bool(self.sheet.toggles.get(f"{entry}{USE_SEP}{use}", default_on))

    def toggled_count(self, group: str) -> int:
        """这个分组里开着的开关类用途有几个（公式 toggled("分组")，例如每个开着的法宝每天多耗法力）。"""
        return sum(
            1
            for entry in self.groups().get(group, ())
            for u in entry.uses
            if u.toggle and self.is_on(entry.name, u.name, u.default_on)
        )

    def modifiers_for(self, name: str) -> list[tuple[Effect, Mapping[str, JsonValue] | None, str]]:
        """作用于某个推导值（或数值字段）的全部带公式的效果，按计算顺序：(效果, 所在条目的字段, 来源说明)。

        固定条目（按分组和条目的定义顺序）→ 玩家写的条目（按 priority 从小到大）→ 状态（按添加先后）。
        """
        out: list[tuple[Effect, Mapping[str, JsonValue] | None, str]] = []
        presets = self._guarded(f"{self.template.name}:presets", self.active_presets)
        # 条目的列按读卡时的值（运行中会变的列带初值和限时修正），例如“开着的时候力量 +2”
        for g in self.template.groups:
            for entry in presets.get(g.name, ()):
                effs = [e for e in entry.effects if e.is_mechanical and e.target == name]
                if effs:
                    cols = self._live_entry(g.name, entry).fields
                    out += [(eff, cols, f"{g.name}:{entry.name}") for eff in effs]
        own: list[tuple[int, int, Effect, Mapping[str, JsonValue], str]] = []
        for group, entries in sorted(self.sheet.groups.items()):
            for entry in entries:
                effs = [e for e in entry.effects if e.is_mechanical and e.target == name]
                if not effs:
                    continue
                cols = self._live_entry(group, entry).fields
                for eff in effs:
                    prio = eff.priority if eff.priority is not None else 1 << 30
                    own.append((prio, len(own), eff, cols, f"{group}:{entry.name}"))
        out += [(eff, fields, src) for _, _, eff, fields, src in sorted(own, key=lambda x: x[:2])]
        # 开着的开关类用途的修正（例如开着风之结界时力量 +1）
        for g in self.template.groups:
            for entry in self.groups().get(g.name, ()):
                for u in entry.uses:
                    if not u.toggle or not self.is_on(entry.name, u.name, u.default_on):
                        continue
                    effs = [e for e in u.effects if e.is_mechanical and e.target == name]
                    if effs:
                        cols = self._live_entry(g.name, entry).fields
                        out += [(eff, cols, f"{g.name}:{entry.name}/{u.name}") for eff in effs]
        for st in self.sheet.statuses:
            eff = st.modifier
            if eff is not None and eff.is_mechanical and eff.target == name:
                out.append((eff, None, f"status:{st.tag}"))
        return out

    def derived(self, name: str) -> DerivedValue:
        cached = self._cache.get(name)
        if cached is not None:
            return cached
        d = self._derived.get(name)
        if d is None:
            raise f.FormulaError("formula.unknown_name", name=name)

        def compute() -> DerivedValue:
            base = self.eval_num(d.formula)
            value = base
            sources: list[str] = []
            # 接力：每个效果的公式里，这个推导值自己的名字是到上一步为止的值
            for eff, entry, src in self.modifiers_for(name):
                assert eff.formula is not None
                value = self.eval_num(eff.formula, entry, overrides={name: value})
                sources.append(src)
            return DerivedValue(name=name, base=base, value=value, modifiers=tuple(sources))

        result = self._guarded(f"{self.template.name}.{name}", compute)
        self._cache[name] = result
        return result

    def field_value(self, name: str, base: float) -> DerivedValue:
        """数值字段经过修正之后的值（例如某个技能让力量高一级、限时的飞行让“能飞”变成是）。"""
        key = f"field:{name}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        def compute() -> DerivedValue:
            value = base
            sources: list[str] = []
            for eff, entry, src in self.modifiers_for(name):
                assert eff.formula is not None
                value = self.eval_num(eff.formula, entry, overrides={name: value})
                sources.append(src)
            return DerivedValue(name=name, base=base, value=value, modifiers=tuple(sources))

        result = self._guarded(f"{self.template.name}.{name}", compute)
        self._cache[key] = result
        return result

    def modified_fields(self) -> list[DerivedValue]:
        """被修正了的数值字段：原值和修正后的值。"""
        out: list[DerivedValue] = []
        for fd in self.template.fields:
            v = as_value(self.sheet.fields.get(fd.name))
            if v is None or isinstance(v, str) or fd.cls != "player":
                continue
            dv = self.field_value(fd.name, v)
            if dv.modifiers:
                out.append(dv)
        return out

    def all_derived(self) -> list[DerivedValue]:
        return [self.derived(d.name) for d in self.template.derived]
