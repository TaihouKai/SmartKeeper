"""Rules 接口的实现。"""

from __future__ import annotations

from pydantic import JsonValue

from smartkeeper.contracts import (
    AdHocCheck,
    CheckResult,
    DerivedValue,
    Dice,
    DiceResult,
    EntityTemplate,
    NotFound,
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
    def __init__(self, dice: Dice) -> None:
        self._dice = dice

    def validate_pack(self, pack: RulePack) -> list[Problem]:
        return validation.validate_pack(pack, self._dice.validate)

    def validate_formula(
        self, pack: RulePack, template: str | None, formula: str, in_entry: str | None = None
    ) -> list[Problem]:
        tpl = pack.template(template) if template else None
        entry_fields: list[str] | None = None
        if tpl is not None and in_entry is not None:
            group = next((g for g in tpl.groups if g.name == in_entry), None)
            entry_fields = [x.name for x in group.fields] if group else []
        extra = validation.CHECK_VARS if template is None else ()
        return validation.check_formula(
            pack, tpl, formula, "formula", entry_fields=entry_fields, extra=extra
        )

    def complete_names(self, pack: RulePack, template: str | None) -> list[str]:
        tpl = pack.template(template) if template else None
        names = validation.known_names(pack, tpl) | set(f.FUNCTIONS)
        names |= {t.name for t in pack.tables}
        return sorted(names)

    def _tpl(self, pack: RulePack, template: str) -> EntityTemplate:
        tpl = pack.template(template)
        if tpl is None:
            raise NotFound("rules.unknown_template", name=template)
        return tpl

    def validate_sheet(self, pack: RulePack, template: str, sheet: JsonValue) -> list[Problem]:
        tpl = pack.template(template)
        if tpl is None:
            return [Problem(code="rules.unknown_template", params={"name": template})]
        return validation.validate_sheet(pack, tpl, sheet)

    def init_sheet(self, pack: RulePack, template: str, sheet: JsonValue) -> JsonValue:
        try:
            return sheets.init_sheet(pack, self._tpl(pack, template), sheet)
        except f.FormulaError as e:
            raise ValidationFailed(e.code, **e.params) from e

    def derive(self, pack: RulePack, template: str, sheet: JsonValue) -> list[DerivedValue]:
        ctx = EntityContext(pack, self._tpl(pack, template), Sheet.model_validate(sheet))
        try:
            return ctx.all_derived()
        except f.FormulaError as e:
            raise ValidationFailed(e.code, **e.params) from e

    def derived_value(self, pack: RulePack, template: str, sheet: JsonValue, name: str) -> float:
        ctx = EntityContext(pack, self._tpl(pack, template), Sheet.model_validate(sheet))
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
