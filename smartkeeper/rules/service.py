"""Rules 接口的实现。"""

from __future__ import annotations

from collections.abc import Mapping

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
from smartkeeper.rules.evaluator import EntityContext
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
    ) -> list[Problem]:
        """other：条目的另一半（校验技能设置时是它的脚本，校验脚本时是它的设置），两边可以互相引用名字。"""
        if scope == "script":
            tpl = pack.template(template) if template else None
            if tpl is None:
                return []
            grp = next((g for g in tpl.groups if g.name == in_entry), None)
            return validation.check_script(
                pack, tpl, formula, "script", [x.name for x in grp.fields] if grp else [], other
            )
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
                [x.name for x in grp.fields] if grp else [],
                other,
            )
        if scope == "dice" and template is not None:
            # 掷骰公式字段：在这个模板（和条目）上求值，可以掷骰
            tpl = pack.template(template)
            fields: list[str] | None = None
            if tpl is not None and in_entry is not None:
                grp = next((g for g in tpl.groups if g.name == in_entry), None)
                fields = [x.name for x in grp.fields] if grp else []
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
            entry_fields = [x.name for x in group.fields] if group else []
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
        )

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
                gcols = [x.name for x in g.fields if x.kind != "param"]
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
            return ctx.all_derived()
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
            return ctx.derived(name).value
        except f.FormulaError as e:
            raise ValidationFailed(e.code, **e.params) from e

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
