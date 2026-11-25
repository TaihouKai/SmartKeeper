"""Rules 接口的实现。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import JsonValue
from pydantic import ValidationError as PydanticError

from smartkeeper import lang as f
from smartkeeper.contracts import (
    AdHocCheck,
    CheckResult,
    CheckSpec,
    DerivedValue,
    DiceResult,
    EntityTemplate,
    Faces,
    FormulaScope,
    GroupDef,
    IntelValue,
    NotFound,
    Peers,
    Problem,
    RulePack,
    ScriptStep,
    Sheet,
    SkillConfig,
    ValidationFailed,
)
from smartkeeper.rules import (
    checkconfig,
    checks,
    scripts,
    sheets,
    skillconfig,
    stealth,
    validation,
)
from smartkeeper.rules import choices as choices_
from smartkeeper.rules.evaluator import EntityContext, as_value
from smartkeeper.rules.render import render as render_markdown


class RulesService:
    def validate_pack(self, pack: RulePack) -> list[Problem]:
        return validation.validate_pack(pack)

    def validate_formula(
        self,
        pack: RulePack,
        template: str | None,
        formula: str,
        in_entry: str | None = None,
        scope: FormulaScope | None = None,
        other: str = "",
        names: Sequence[str] = (),
    ) -> list[Problem]:
        """other：条目的另一半（校验技能设置时是它的脚本，校验脚本时是它的设置），两边可以互相引用名字。
        names：条目里另外能用 this.<名字> 的（条目和用途自己加的参数）。"""

        def cols(grp: GroupDef | None) -> list[str]:
            if grp is None:
                return list(names)
            own = [x.name for x in grp.fields]
            return [*own, *(x.name for x in validation.group_params(pack, grp.name)), *names]

        if scope == "script":
            tpl = pack.template(template) if template else None
            if tpl is None:
                return []
            grp = next((g for g in tpl.groups if g.name == in_entry), None)
            return validation.check_script(pack, tpl, formula, "script", cols(grp), other)
        if scope == "check":
            return validation.check_check(pack, formula, "check")
        if scope in ("stealth", "search"):
            return validation.check_stealth(
                pack, pack.template(template) if template else None, formula, "formula", scope
            )
        if scope == "damage":
            return validation.check_formula(
                pack,
                pack.template(template) if template else None,
                formula,
                "formula",
                extra=validation.DAMAGE_VARS,
            )
        if scope == "config":
            tpl = pack.template(template) if template else None
            if tpl is None:
                return []
            grp = next((g for g in tpl.groups if g.name == in_entry), None)
            return validation.check_config(
                pack,
                tpl,
                grp,
                formula,
                "config",
                cols(grp),
                other,
            )
        if scope == "dice" and template is not None:
            # 掷骰公式字段：在这个模板（和条目）上求值，可以掷骰
            tpl = pack.template(template)
            fields: list[str] | None = None
            if tpl is not None and in_entry is not None:
                grp = next((g for g in tpl.groups if g.name == in_entry), None)
                fields = cols(grp)
            return validation.check_formula(
                pack, tpl, formula, "formula", entry_fields=fields, dice=True
            )
        if scope is not None:
            extra = validation.all_field_names(pack)
            return validation.check_formula(
                pack, None, formula, "formula", extra=extra, dice=scope == "dice"
            )
        tpl = pack.template(template) if template else None
        entry_fields: list[str] | None = None
        if tpl is not None and in_entry is not None:
            group = next((g for g in tpl.groups if g.name == in_entry), None)
            entry_fields = cols(group)
        extra = validation.CHECK_VARS if template is None else ()
        return validation.check_formula(
            pack, tpl, formula, "formula", entry_fields=entry_fields, extra=extra
        )

    def roll(
        self,
        pack: RulePack,
        expr: str,
        faces: Faces,
        template: str | None = None,
        sheet: JsonValue = None,
        entry: dict[str, JsonValue] | None = None,
        peers: Peers | None = None,
        target: tuple[str, JsonValue, Peers | None] | None = None,
        extra: Mapping[str, float] | None = None,
    ) -> DiceResult:
        return checks.roll(pack, expr, faces, template, sheet, entry, peers, target, extra)

    def plan_script(
        self,
        pack: RulePack,
        script: str,
        faces: Faces,
        template: str,
        sheet: JsonValue,
        entry: dict[str, JsonValue],
        peers: Peers | None = None,
        target: tuple[str, JsonValue, Peers | None] | None = None,
        config: str = "",
        outcome: Mapping[str, float] | None = None,
        damage_kind: str = "",
        scale: float = 1.0,
    ) -> tuple[ScriptStep, ...]:
        return scripts.plan_script(
            pack,
            script,
            faces,
            template,
            sheet,
            entry,
            peers,
            target,
            config,
            outcome,
            damage_kind,
            scale,
        )

    def choice_allowed(self, choices: tuple[str, ...], value: float) -> bool:
        try:
            return choices_.allowed(choices, value)
        except ValueError:
            return False

    def first_choice(self, choices: tuple[str, ...]) -> float | None:
        try:
            values, ranges = choices_.parse(choices)
        except ValueError:
            return None
        if values:
            return values[0][1]
        return ranges[0][0] if ranges else None

    def skill_config(self, config: str, script: str = "") -> SkillConfig:
        try:
            return skillconfig.read_config(config, script)
        except f.FormulaError as e:
            raise ValidationFailed(e.code, **e.params) from e

    def complete_names(
        self, pack: RulePack, template: str | None, scope: FormulaScope | None = None
    ) -> list[str]:
        tpl = pack.template(template) if template else None
        names = (
            validation.known_names(pack, tpl)
            | set(f.FUNCTIONS)
            | {"and", "or", "not", "if", "else"}
        )
        if tpl is not None:
            mine = validation.known_names(pack, tpl) - {x.name for x in pack.formulas}
            names |= {f"self.{n}" for n in mine} | {"self.template"}
            names |= {f"this.{x.name}" for g in tpl.groups for x in g.fields}
            names |= {f"this.{p.name}" for p in pack.params}  # 默认参数
            for pid, cols in validation.preset_ids(tpl).items():
                names.add(f"self.{pid}")
                names |= {f"self.{pid}.{c}" for c in cols}
        if scope == "script":
            whos = (*f.RECEIVERS, *(t.name for t in pack.templates))
            names |= {f"{who}.{verb}" for who in whos for verb in f.VERBS}
            names |= {"elif", "pass"}
        if scope == "damage":
            names |= set(validation.DAMAGE_VARS)
        if scope in ("stealth", "search"):
            names |= set(stealth.VARS)
        if scope == "check":
            names |= (
                set(checkconfig.KEYS) | set(checkconfig.VARS) | validation.all_field_names(pack)
            )
            names |= {"True", "False", "None"}
        if scope == "config":
            names |= (
                set(skillconfig.KEYS)
                | set(skillconfig.SHAPES)
                | {"placement", "None", "True", "False"}
            )
        names |= {t.name for t in pack.tables}
        # 引用写法：<模板>.字段/推导值、<模板>.<固定条目ID>、<模板>.<固定条目ID>.<列>、target.x、
        # 分组引用（count / sum）：分组、分组.列、<模板>.分组.列、target.分组.列
        names.add("target.template")
        for t in pack.templates:
            plain = validation.known_names(pack, t) - {x.name for x in pack.formulas}
            names |= {f"{t.name}.{n}" for n in plain} | {f"{t.name}.template"}
            names |= {f"target.{n}" for n in plain}
            for g in t.groups:
                gcols = [x.name for x in g.fields]
                for head in (t.name, "target", ""):
                    ref = f"{head}.{g.name}" if head else g.name
                    names.add(ref)
                    names |= {f"{ref}.{c}" for c in gcols}
            for pid, cols in validation.preset_ids(t).items():
                for head in (t.name, "target"):
                    names.add(f"{head}.{pid}")
                    names |= {f"{head}.{pid}.{c}" for c in cols}
        return sorted(names)

    def _tpl(self, pack: RulePack, template: str) -> EntityTemplate:
        tpl = pack.template(template)
        if tpl is None:
            raise NotFound("rules.unknown_template", name=template)
        return tpl

    def validate_sheet(
        self, pack: RulePack, template: str, sheet: JsonValue, peers: Peers | None = None
    ) -> list[Problem]:
        tpl = pack.template(template)
        if tpl is None:
            return [Problem(code="rules.unknown_template", params={"name": template})]
        return validation.validate_sheet(pack, tpl, sheet, peers)

    def init_sheet(
        self, pack: RulePack, template: str, sheet: JsonValue, peers: Peers | None = None
    ) -> JsonValue:
        try:
            return sheets.init_sheet(pack, self._tpl(pack, template), sheet, peers)
        except f.FormulaError as e:
            raise ValidationFailed(e.code, **e.params) from e

    def full_sheet(
        self, pack: RulePack, template: str, sheet: JsonValue, peers: Peers | None = None
    ) -> JsonValue:
        tpl = pack.template(template)
        if tpl is None:
            return sheet
        try:
            parsed = Sheet.model_validate(sheet)
        except PydanticError:
            return sheet
        ctx = EntityContext(pack, tpl, parsed, peers=peers or {})
        return ctx.full_sheet().model_dump(mode="json")

    def derive(
        self, pack: RulePack, template: str, sheet: JsonValue, peers: Peers | None = None
    ) -> list[DerivedValue]:
        ctx = EntityContext(
            pack, self._tpl(pack, template), Sheet.model_validate(sheet), peers=peers or {}
        )
        try:
            # 被修正了的数值字段也列出来（例如被技能提高了的力量），排在推导值后面
            return ctx.all_derived() + ctx.modified_fields()
        except f.FormulaError as e:
            raise ValidationFailed(e.code, **e.params) from e

    def derived_value(
        self,
        pack: RulePack,
        template: str,
        sheet: JsonValue,
        name: str,
        peers: Peers | None = None,
    ) -> float:
        ctx = EntityContext(
            pack, self._tpl(pack, template), Sheet.model_validate(sheet), peers=peers or {}
        )
        try:
            if any(d.name == name for d in ctx.template.derived):
                return ctx.derived(name).value
            v = ctx.value_of(name)  # 字段：经过修正之后的值
            if isinstance(v, str):
                raise f.FormulaError("formula.text_result", value=v)
            return v
        except f.FormulaError as e:
            raise ValidationFailed(e.code, **e.params) from e

    def describe(
        self,
        pack: RulePack,
        template: str,
        sheet: JsonValue,
        names: tuple[str, ...],
        peers: Peers | None = None,
    ) -> tuple[IntelValue, ...]:
        tpl = self._tpl(pack, template)
        ctx = EntityContext(pack, tpl, Sheet.model_validate(sheet), peers=peers or {})
        fdefs = {x.name: x for x in tpl.fields}
        ddefs = {d.name: d for d in tpl.derived}
        out: list[IntelValue] = []
        for n in names:
            fd, dd = fdefs.get(n), ddefs.get(n)
            if fd is None and dd is None:
                continue
            try:
                v = ctx.value_of(n)
            except f.FormulaError:
                continue
            label = (fd.label if fd else dd.label if dd else "") or n
            out.append(
                _intel_value(n, label, v, fd.kind if fd else "number", fd.choices if fd else ())
            )
        return tuple(out)

    def describe_entries(
        self,
        pack: RulePack,
        template: str,
        sheet: JsonValue,
        group: str,
        peers: Peers | None = None,
    ) -> tuple[tuple[str, tuple[IntelValue, ...]], ...]:
        tpl = self._tpl(pack, template)
        gdef = next((g for g in tpl.groups if g.name == group), None)
        if gdef is None:
            return ()
        ctx = EntityContext(pack, tpl, Sheet.model_validate(sheet), peers=peers or {})
        try:
            entries = ctx.groups().get(group, ())
        except f.FormulaError:
            return ()
        cols = [x for x in gdef.fields if x.cls == "player" and not x.hidden]
        out: list[tuple[str, tuple[IntelValue, ...]]] = []
        for e in entries:
            vals: list[IntelValue] = []
            for fd in cols:
                raw = e.fields.get(fd.name)
                v = as_value(raw)
                if v is None:
                    continue
                vals.append(_intel_value(fd.name, fd.label or fd.name, v, fd.kind, fd.choices))
            out.append((e.name, tuple(vals)))
        return tuple(out)

    def check_dice(self, pack: RulePack, check: str) -> str:
        return checks.check_dice(pack, check)

    def check_spec(self, pack: RulePack, name: str) -> CheckSpec:
        return checks.spec(pack, name)

    def resolve_check(
        self,
        pack: RulePack,
        *,
        entity: str,
        template: str,
        sheet: JsonValue,
        check: str,
        roll: DiceResult,
        difficulty: float | None = None,
        opponent: tuple[str, str, JsonValue, DiceResult] | None = None,
        peers: Peers | None = None,
        opp_check: str | None = None,
        distance: float = 0.0,
        vs_template: str = "",
    ) -> CheckResult:
        return checks.resolve_check(
            pack,
            entity=entity,
            template=template,
            sheet=sheet,
            check=check,
            roll=roll,
            difficulty=difficulty,
            opponent=opponent,
            peers=peers,
            opp_check=opp_check,
            distance=distance,
            vs_template=vs_template,
        )

    def stealth(
        self,
        pack: RulePack,
        hider: tuple[str, JsonValue, Peers | None],
        observer: tuple[str, JsonValue, Peers | None],
        distance: float,
    ) -> float:
        return stealth.stealth(pack, hider, observer, distance)

    def resolve_adhoc(self, entity: str, spec: AdHocCheck, roll: DiceResult) -> CheckResult:
        if spec.success_when == "roll<=target":
            ok = roll.total <= spec.target
        else:
            ok = roll.total >= spec.target
        return CheckResult(
            entity=entity,
            check="adhoc",
            roll=roll,
            target=spec.target,
            level=1 if ok else 0,
        )

    def render(self, pack: RulePack) -> str:
        return render_markdown(pack)


def _intel_value(
    name: str, label: str, v: f.Value, kind: str, choices: tuple[str, ...]
) -> IntelValue:
    if isinstance(v, str):
        return IntelValue(name=name, label=label, value=v)
    if kind == "boolean":
        return IntelValue(name=name, label=label, value=v != 0)
    num: JsonValue = int(v) if float(v).is_integer() else round(v, 2)
    return IntelValue(name=name, label=label, value=num, shown=choices_.label_of(choices, v))
