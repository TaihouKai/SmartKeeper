import { useCallback } from "react";
import type { Schemas } from "../api/client";
import { useI18n } from "../i18n";
import type { ReactNode } from "react";
import { FormulaInput, Mover, moved } from "./components";

type FieldDef = Schemas["FieldDef"];
type GroupDef = Schemas["GroupDef"];

// formula 算出 target 的新值；写 target 自己的名字表示到这一步为止的值。priority 只有玩家写的效果才有
export type Effect = { description: string; target: string | null; formula: string | null; priority?: number | null };
export type Shape = { kind: "capsule" | "box" | "sphere" | "cone"; length?: number | null; width?: number | null; height?: number | null; radius?: number | null; angle?: number | null };
export type Entry = { name: string; description: string; fields: Record<string, string | number | boolean>; effects: Effect[]; shape: Shape | null };

type Check = (f: string) => Promise<{ problems: { code: string }[]; names: string[] }>;

export function FieldInput({ def, value, onChange, validateFormula }: { def: FieldDef; value: string | number | boolean | undefined; onChange: (v: string | number | boolean) => void; validateFormula?: Check }) {
  const { t } = useI18n();
  if (def.kind === "formula") {
    // 掷骰公式（例如伤害 1d str）：平时不算，KP 裁定时才掷
    return validateFormula ? (
      <FormulaInput value={typeof value === "string" ? value : ""} validate={validateFormula} placeholder={t("rules.ph.dice")} onChange={(v) => onChange(v)} />
    ) : (
      <input value={typeof value === "string" ? value : ""} onChange={(e) => onChange(e.target.value)} />
    );
  }
  if (def.kind === "boolean") {
    return <input type="checkbox" checked={value === true} onChange={(e) => onChange(e.target.checked)} />;
  }
  if (def.kind === "text") {
    if (def.choices && def.choices.length) {
      return (
        <select value={String(value ?? "")} onChange={(e) => onChange(e.target.value)}>
          <option value="" />
          {def.choices.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      );
    }
    return <textarea rows={2} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} />;
  }
  return (
    <input
      type="number"
      value={value === undefined ? "" : String(value)}
      onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))}
    />
  );
}

export function fieldLabel(f: { name: string; label?: string; unit?: string | null }) {
  return `${f.label || f.name}${f.unit ? ` (${f.unit})` : ""}`;
}

/** 分组里的一个条目：名字、说明、字段、效果、范围形状。建角和规则包的固定条目共用。 */
export function EntryEditor({
  group,
  derived,
  entry,
  onChange,
  onRemove,
  validate,
  withPriority = true,
  mover,
}: {
  group: GroupDef;
  derived: string[];
  entry: Entry;
  onChange: (e: Entry) => void;
  onRemove?: () => void;
  validate: (f: string, inEntry: string, dice?: boolean) => Promise<{ problems: { code: string }[]; names: string[] }>;
  /** 玩家写的条目要给效果填计算顺序；规则包的固定条目按定义顺序，不用填 */
  withPriority?: boolean;
  mover?: ReactNode;
}) {
  const { t } = useI18n();
  const fields = group.fields ?? [];
  const shapes = group.shapes?.allowed ?? [];
  const v = useCallback((f: string) => validate(f, group.name), [validate, group.name]);
  const vDice = useCallback((f: string) => validate(f, group.name, true), [validate, group.name]);
  return (
    <div className="sk-entry">
      {mover && <div className="sk-row sk-row-end">{mover}</div>}
      <label>
        {t("character.entry_name")}
        <input value={entry.name} onChange={(e) => onChange({ ...entry, name: e.target.value })} />
      </label>
      <label>
        {t("character.entry_description")}
        <textarea rows={2} value={entry.description} onChange={(e) => onChange({ ...entry, description: e.target.value })} />
      </label>
      {fields.map((f) => (
        <label key={f.name}>
          {fieldLabel(f)}
          {f.description && <small className="sk-field-desc">{f.description}</small>}
          <FieldInput def={f} value={entry.fields[f.name]} validateFormula={vDice} onChange={(val) => onChange({ ...entry, fields: { ...entry.fields, [f.name]: val } })} />
        </label>
      ))}
      {group.effects !== false && (
        <div className="sk-effects">
          <strong>{t("character.effects")}</strong>
          {entry.effects.map((ef, i) => (
            <div key={i} className="sk-effect">
              <input placeholder={t("character.effect_description")} value={ef.description} onChange={(e) => onChange({ ...entry, effects: entry.effects.map((x, j) => (j === i ? { ...x, description: e.target.value } : x)) })} />
              <select value={ef.target ?? ""} onChange={(e) => onChange({ ...entry, effects: entry.effects.map((x, j) => (j === i ? { ...x, target: e.target.value || null, formula: e.target.value ? (x.formula ?? e.target.value) : null } : x)) })}>
                <option value="">{t("character.effect_conceptual")}</option>
                {derived.map((d) => (
                  <option key={d} value={d}>
                    {d}
                  </option>
                ))}
              </select>
              {ef.target && (
                <>
                  <span className="sk-hint sk-eq">=</span>
                  <FormulaInput value={ef.formula ?? ""} validate={v} placeholder={t("character.effect_formula", { name: ef.target })} onChange={(val) => onChange({ ...entry, effects: entry.effects.map((x, j) => (j === i ? { ...x, formula: val } : x)) })} />
                  {withPriority && (
                    <label className="sk-inline sk-priority">
                      {t("character.effect_priority")}
                      <input type="number" min={0} className="sk-small" value={ef.priority ?? ""} onChange={(e) => onChange({ ...entry, effects: entry.effects.map((x, j) => (j === i ? { ...x, priority: e.target.value === "" ? null : Math.max(0, Math.floor(Number(e.target.value))) } : x)) })} />
                    </label>
                  )}
                </>
              )}
              <Mover index={i} count={entry.effects.length} onMove={(from, to) => onChange({ ...entry, effects: moved(entry.effects, from, to) })} />
              <button type="button" className="sk-link" onClick={() => onChange({ ...entry, effects: entry.effects.filter((_, j) => j !== i) })}>
                {t("common.remove")}
              </button>
            </div>
          ))}
          <button type="button" onClick={() => onChange({ ...entry, effects: [...entry.effects, { description: "", target: null, formula: null, priority: null }] })}>
            {t("character.add_effect")}
          </button>
          {entry.effects.some((x) => x.target) && <p className="sk-hint">{t(withPriority ? "character.effect_hint" : "character.effect_hint_fixed")}</p>}
        </div>
      )}
      {shapes.length > 0 && (
        <div className="sk-shape">
          <strong>{t("character.shape")}</strong>
          <select value={entry.shape?.kind ?? ""} onChange={(e) => onChange({ ...entry, shape: e.target.value ? { kind: e.target.value as Shape["kind"] } : null })}>
            <option value="">{t("character.shape_none")}</option>
            {shapes.map((s) => (
              <option key={s} value={s}>
                {t(`shape.${s}`)}
              </option>
            ))}
          </select>
          {entry.shape &&
            (["length", "width", "height", "radius", "angle"] as const).map((k) => (
              <label key={k}>
                {t(`shape.${k}`)}
                <input type="number" value={entry.shape?.[k] ?? ""} onChange={(e) => onChange({ ...entry, shape: { ...(entry.shape as Shape), [k]: e.target.value === "" ? null : Number(e.target.value) } })} />
              </label>
            ))}
        </div>
      )}
      {onRemove && (
        <button type="button" className="sk-link" onClick={onRemove}>
          {t("character.remove_entry")}
        </button>
      )}
    </div>
  );
}
