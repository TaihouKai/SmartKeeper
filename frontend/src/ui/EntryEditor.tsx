import { useCallback, useState } from "react";
import type { Schemas } from "../api/client";
import { useI18n } from "../i18n";
import type { ReactNode } from "react";
import { FormulaInput, Mover, moved } from "./components";
import { CodeEditor } from "./CodeEditor";
import { fillConfig } from "./skillConfig";

type FieldDef = Schemas["FieldDef"];
type GroupDef = Schemas["GroupDef"];

// formula 算出 target 的新值；写 target 自己的名字表示到这一步为止的值。priority 只有玩家写的效果才有
export type Effect = { description: string; target: string | null; formula: string | null; priority?: number | null };
export type Entry = { name: string; id?: string; description: string; fields: Record<string, string | number | boolean>; effects: Effect[]; config?: string; script?: string };

type Check = (f: string) => Promise<{ problems: { code: string }[]; names: string[] }>;

export function FieldInput({ def, value, onChange, validateFormula, onExpand }: { def: FieldDef; value: string | number | boolean | undefined; onChange: (v: string | number | boolean) => void; validateFormula?: Check; onExpand?: () => void }) {
  const { t } = useI18n();
  if (def.kind === "param") {
    // 使用时填写（例如这次消耗多少魔力）：建角时不填，行动里说
    return <span className="sk-hint">{t("character.param_field", { min: def.min ?? "-", max: def.max ?? "-" })}</span>;
  }
  if (def.kind === "formula") {
    // 掷骰公式（例如伤害 1d str）：平时不算，KP 裁定时才掷
    return validateFormula ? (
      <FormulaInput value={typeof value === "string" ? value : ""} validate={validateFormula} placeholder={t("rules.ph.dice")} onChange={(v) => onChange(v)} onExpand={onExpand} />
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

/** 字段在表单上的标签。还没起名字的字段（规则面板里刚加的）显示提示，而不是一个空标签。 */
export function fieldLabel(f: { name: string; label?: string; unit?: string | null }, unnamed = "?") {
  return `${f.label || f.name || unnamed}${f.unit ? ` (${f.unit})` : ""}`;
}

/** 分组里的一个条目：名字、说明、字段、修正、技能脚本、范围形状。建角和规则包的固定条目共用。 */
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
  validate: (f: string, inEntry: string, scope?: "dice" | "script" | "config", other?: string) => Promise<{ problems: { code: string }[]; names: string[] }>;
  /** 玩家写的条目要给效果填计算顺序；规则包的固定条目按定义顺序，不用填 */
  withPriority?: boolean;
  mover?: ReactNode;
}) {
  const { t } = useI18n();
  const fields = group.fields ?? [];
  const v = useCallback((f: string) => validate(f, group.name), [validate, group.name]);
  const vDice = useCallback((f: string) => validate(f, group.name, "dice"), [validate, group.name]);
  // 设置和脚本可以互相引用名字：校验一边时带上另一边
  const vScript = useCallback((f: string) => validate(f, group.name, "script", entry.config ?? ""), [validate, group.name, entry.config]);
  const vConfig = useCallback((f: string) => validate(f, group.name, "config", entry.script ?? ""), [validate, group.name, entry.script]);
  return (
    <div className="sk-entry">
      {mover && <div className="sk-row sk-row-end">{mover}</div>}
      <label>
        {t("character.entry_name")}
        <input value={entry.name} onChange={(e) => onChange({ ...entry, name: e.target.value })} />
      </label>
      <label>
        {t("rules.gt.id")}
        <small className="sk-field-desc">{t("rules.gt.id_hint")}</small>
        <input value={entry.id ?? ""} placeholder={t("rules.gt.id_ph")} onChange={(e) => onChange({ ...entry, id: e.target.value.trim() })} />
      </label>
      <label>
        {t("character.entry_description")}
        <textarea rows={2} value={entry.description} onChange={(e) => onChange({ ...entry, description: e.target.value })} />
      </label>
      {fields.map((f) => (
        <label key={f.name}>
          {fieldLabel(f, t("character.unnamed_field"))}
          {f.kind === "formula" && <small className="sk-field-desc">{t("character.formula_field")}</small>}
          {f.description && <small className="sk-field-desc">{f.description}</small>}
          <FieldInput def={f} value={entry.fields[f.name]} validateFormula={vDice} onChange={(val) => onChange({ ...entry, fields: { ...entry.fields, [f.name]: val } })} />
        </label>
      ))}
      {group.effects !== false && <EffectsEditor effects={entry.effects} derived={derived} validate={v} withPriority={withPriority} onChange={(effects) => onChange({ ...entry, effects })} />}
      {group.effects !== false && <ConfigEditor config={entry.config || fillConfig("", group, t)} validate={vConfig} onChange={(config) => onChange({ ...entry, config })} />}
      {group.effects !== false && <ScriptEditor script={entry.script ?? ""} validate={vScript} onChange={(script) => onChange({ ...entry, script })} />}
      {onRemove && (
        <button type="button" className="sk-link" onClick={onRemove}>
          {t("character.remove_entry")}
        </button>
      )}
    </div>
  );
}

/** 一个条目的修正列表（一直生效）：描述、作用于哪个推导值、新值的公式；玩家写的还要填计算顺序。 */
export function EffectsEditor({
  effects,
  derived,
  validate,
  withPriority,
  onChange,
}: {
  effects: Effect[];
  derived: string[];
  validate: Check;
  withPriority: boolean;
  onChange: (effects: Effect[]) => void;
}) {
  const { t } = useI18n();
  const set = (i: number, patch: Partial<Effect>) => onChange(effects.map((x, j) => (j === i ? { ...x, ...patch } : x)));
  return (
    <div className="sk-effects">
      <strong>{t("character.effects")}</strong>
      {effects.map((ef, i) => (
        <div key={i} className="sk-effect">
          <input placeholder={t("character.effect_description")} value={ef.description} onChange={(e) => set(i, { description: e.target.value })} />
          <select value={ef.target ?? ""} onChange={(e) => set(i, { target: e.target.value || null, formula: e.target.value ? (ef.formula ?? e.target.value) : null })}>
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
              <FormulaInput value={ef.formula ?? ""} validate={validate} placeholder={t("character.effect_formula", { name: ef.target })} onChange={(val) => set(i, { formula: val })} />
              {withPriority && (
                <label className="sk-inline sk-priority">
                  {t("character.effect_priority")}
                  <input type="number" min={0} className="sk-small" value={ef.priority ?? ""} onChange={(e) => set(i, { priority: e.target.value === "" ? null : Math.max(0, Math.floor(Number(e.target.value))) })} />
                </label>
              )}
            </>
          )}
          <Mover index={i} count={effects.length} onMove={(from, to) => onChange(moved(effects, from, to))} />
          <button type="button" className="sk-link" onClick={() => onChange(effects.filter((_, j) => j !== i))}>
            {t("common.remove")}
          </button>
        </div>
      ))}
      <button type="button" onClick={() => onChange([...effects, { description: "", target: null, formula: null, priority: null }])}>
        {t("character.add_effect")}
      </button>
      {effects.some((x) => x.target) && <p className="sk-hint">{t(withPriority ? "character.effect_hint" : "character.effect_hint_fixed")}</p>}
    </div>
  );
}

/** 技能设置：一串 名字 = 值（对象、射程、施放时间、冷却、范围形状……），引擎按它执行。 */
export function ConfigEditor({ config, validate, onChange }: { config: string; validate: Check; onChange: (s: string) => void }) {
  const { t } = useI18n();
  const [problems, setProblems] = useState<string[]>([]);
  return (
    <div className="sk-effects sk-script">
      <strong>{t("config.title")}</strong>
      <CodeEditor className="sk-code-inline" value={config} check={validate} minLines={3} onChange={onChange} onProblems={setProblems} />
      {problems.length > 0 && <small className="sk-invalid">{problems.join("; ")}</small>}
      <p className="sk-hint">{t("config.hint")}</p>
    </div>
  );
}

/** 技能脚本：用这个条目（并且 KP 判定生效）时引擎执行的语句，一行一句。 */
export function ScriptEditor({ script, validate, onChange }: { script: string; validate: Check; onChange: (s: string) => void }) {
  const { t } = useI18n();
  const [problems, setProblems] = useState<string[]>([]);
  return (
    <div className="sk-effects sk-script">
      <strong>{t("script.title")}</strong>
      <CodeEditor className="sk-code-inline" value={script} check={validate} placeholder={t("script.ph")} minLines={4} onChange={onChange} onProblems={setProblems} />
      {problems.length > 0 && <small className="sk-invalid">{problems.join("; ")}</small>}
      <p className="sk-hint">{t("script.hint")}</p>
    </div>
  );
}
