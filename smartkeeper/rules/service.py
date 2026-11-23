"""Rules 接口的实现。"""

from __future__ import annotations

from pydantic import JsonValue
from pydantic import ValidationError as PydanticError

from smartkeeper.contracts import (
    AdHocCheck,
    CheckResult,
    DerivedValue,
    DiceResult,
    EntityTemplate,
    Faces,
    FormulaScope,
    NotFound,
    Peers,
    Problem,
    RulePack,
    Sheet,
    ValidationFailed,
)
from smartkeeper.rules import checks, sheets, validation
from smartkeeper.rules import formula as f
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
    ) -> list[Problem]:
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
    ) -> DiceResult:
        return checks.roll(pack, expr, faces, template, sheet, entry, peers, target)

    def freeze(
        self,
        pack: RulePack,
        formula: str,
        template: str,
        sheet: JsonValue,
        entry: dict[str, JsonValue] | None,
        peers: Peers | None,
        keep: str,
        target: tuple[str, JsonValue, Peers | None] | None = None,
    ) -> str:
        return checks.freeze(pack, formula, template, sheet, entry, peers, keep, target)

    def complete_names(self, pack: RulePack, template: str | None) -> list[str]:
        tpl = pack.template(template) if template else None
        names = validation.known_names(pack, tpl) | set(f.FUNCTIONS)
        names |= {t.name for t in pack.tables}
        # 引用写法：<模板>.字段/推导值、<模板>.<固定条目ID>、<模板>.<固定条目ID>.<列>、target.x
        for t in pack.templates:
            plain = validation.known_names(pack, t) - {x.name for x in pack.formulas}
            names |= {f"{t.name}.{n}" for n in plain}
            names |= {f"target.{n}" for n in plain}
            for g in t.groups:
                gcols = [x.name for x in g.fields if x.kind != "param"]
                names |= {f"{t.name}.{g.name}.{c}" for c in gcols}
                names |= {f"{g.name}.{c}" for c in gcols}
            for pid, cols in validation.preset_ids(t).items():
                names.add(f"{t.name}.{pid}")
                names |= {f"{t.name}.{pid}.{c}" for c in cols}
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
        )

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
            level="success" if ok else "failure",
        )

    def render(self, pack: RulePack) -> str:
        return render_markdown(pack)
