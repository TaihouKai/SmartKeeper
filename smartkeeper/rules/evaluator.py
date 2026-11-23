"""在一张角色卡上求值公式与推导值。纯函数：同一张卡加同一个规则包，结果永远相同。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from pydantic import JsonValue

from smartkeeper.contracts import DerivedValue, Effect, EntityTemplate, GroupEntry, RulePack, Sheet
from smartkeeper.rules import formula as f


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
        self._groups: dict[str, tuple[GroupEntry, ...]] | None = None

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
                hits.append(GroupEntry.model_validate(p.model_dump(exclude={"when"})))
            if hits:
                out[g.name] = tuple(hits)
        return out

    def groups(self) -> dict[str, tuple[GroupEntry, ...]]:
        if self._groups is None:
            merged = dict(self.sheet.groups)
            guard = f"{self.template.name}:presets"
            for name, presets in self._guarded(guard, self.active_presets).items():
                merged[name] = presets + merged.get(name, ())
            self._groups = merged
        return self._groups

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
            if name.startswith("self."):
                if entry is None:
                    raise f.FormulaError("formula.self_outside_entry", name=name)
                key = name[5:]
                if key not in entry:
                    raise f.FormulaError("formula.unknown_name", name=name)
                v = as_value(entry[key])
                if v is None:
                    raise f.FormulaError("formula.bad_value", name=name)
                return v
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
        """<模板>.x、target.x：自己这边的实体、作用对象的字段、推导值和条目。"""
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

    def member(self, rest: list[str], full: str) -> f.Value:
        if rest == ["template"]:
            return self.template.name
        if len(rest) == 1:
            key = rest[0]
            if (
                key in self.extra
                or key in self._derived
                or key in self.sheet.fields
                or key in self._formulas
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
        if name in self.sheet.fields:
            v = as_value(self.sheet.fields[name])
            if v is None:
                raise f.FormulaError("formula.bad_value", name=name)
            return v
        if name in self._formulas:
            key = f"{self.template.name}.{name}"
            return self._guarded(key, lambda: self.eval(self._formulas[name].formula))
        raise f.FormulaError("formula.unknown_name", name=name)

    def eval(
        self,
        text: str,
        entry: Mapping[str, JsonValue] | None = None,
        faces: f.Faces | None = None,
        overrides: Mapping[str, f.Value] | None = None,
    ) -> f.Value:
        return f.evaluate(f.parse(text), self.resolver(entry, overrides), self._lookup, faces)

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

    def modifiers_for(self, name: str) -> list[tuple[Effect, Mapping[str, JsonValue] | None, str]]:
        """作用于某个推导值的全部带公式的效果，按计算顺序：(效果, 所在条目的字段, 来源说明)。

        固定条目（按分组和条目的定义顺序）→ 玩家写的条目（按 priority 从小到大）→ 状态（按添加先后）。
        """
        out: list[tuple[Effect, Mapping[str, JsonValue] | None, str]] = []
        presets = self._guarded(f"{self.template.name}:presets", self.active_presets)
        for g in self.template.groups:
            for entry in presets.get(g.name, ()):
                for eff in entry.effects:
                    if eff.is_mechanical and eff.target == name:
                        out.append((eff, entry.fields, f"{g.name}:{entry.name}"))
        own: list[tuple[int, int, Effect, Mapping[str, JsonValue], str]] = []
        for group, entries in sorted(self.sheet.groups.items()):
            for entry in entries:
                for eff in entry.effects:
                    if eff.is_mechanical and eff.target == name:
                        prio = eff.priority if eff.priority is not None else 1 << 30
                        own.append((prio, len(own), eff, entry.fields, f"{group}:{entry.name}"))
        out += [(eff, fields, src) for _, _, eff, fields, src in sorted(own, key=lambda x: x[:2])]
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

    def all_derived(self) -> list[DerivedValue]:
        return [self.derived(d.name) for d in self.template.derived]
