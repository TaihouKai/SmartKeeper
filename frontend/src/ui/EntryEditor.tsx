import { useCallback, useState } from "react";
import type { Schemas } from "../api/client";
import { useI18n } from "../i18n";
import type { ReactNode } from "react";
import { FormulaInput, Mover, moved } from "./components";
import { CodeEditor } from "./CodeEditor";
import { numberOptions } from "./choices";
import { Described } from "./markdown";
import { fillConfig, mergeConfig } from "./skillConfig";

/** 多行的提示：第一行是一句话，后面每行一条（以 - 开头的显示成列表）。 */
function Hint({ text }: { text: string }) {
  const lines = text.split("\n").filter((x) => x.trim());
  const items = lines.filter((x) => x.startsWith("- "));
  const rest = lines.filter((x) => !x.startsWith("- "));
  return (
    <div className="sk-hint sk-hint-block">
      {rest.map((x, i) => (
        <p key={i}>{x}</p>
      ))}
      {items.length > 0 && (
        <ul>
          {items.map((x, i) => (
            <li key={i}>
              <code>{x.slice(2).split("：")[0]}</code>
              {x.includes("：") ? `：${x.slice(2).split("：").slice(1).join("：")}` : ""}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

type FieldDef = Schemas["FieldDef"];
type GroupDef = Schemas["GroupDef"];

// formula 算出 target 的新值；写 target 自己的名字表示到这一步为止的值。priority 只有玩家写的效果才有
export type Effect = { description: string; target: string | null; formula: string | null; priority?: number | null };
export type Use = { name: string; description?: string; config?: string; script?: string };
export type Entry = { name: string; id?: string; description: string; fields: Record<string, string | number | boolean>; effects: Effect[]; config?: string; script?: string; uses?: Use[] };

type Check = (f: string) => Promise<{ problems: { code: string }[]; names: string[] }>;

export function FieldInput({ def, value, onChange, validateFormula, onExpand }: { def: FieldDef; value: string | number | boolean | undefined; onChange: (v: string | number | boolean) => void; validateFormula?: Check; onExpand?: () => void }) {
  const { t } = useI18n();
  if (def.kind === "param") {
    // 使用时填写（例如这次消耗多少魔力、要不要解放）：建角时不填，行动里说
    if (def.choices && def.choices.length) return <span className="sk-hint">{t("character.param_choices", { choices: def.choices.join("、") })}</span>;
    return <span className="sk-hint">{t("character.param_field", { min: def.min ?? "-", max: def.max ?? "-" })}</span>;
  }
  if (def.cls === "runtime") {
    // 条目运行中会变的列（例如开着没有、还剩几发）：游戏里由技能改，建角时不填
    return <span className="sk-hint">{t("character.runtime_column")}</span>;
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
  if (def.choices && def.choices.length) {
    // 数值的可选值（例如 E=1 … EX=10）：下拉选，存的是数
    return (
      <select value={value === undefined || value === "" ? "" : String(value)} onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))}>
        <option value="" />
        {numberOptions(def.choices).map((o) => (
          <option key={o.value} value={String(o.value)}>
            {o.label ? `${o.label}（${o.value}）` : o.value}
          </option>
        ))}
      </select>
    );
  }
  const lo = def.min && /^\s*-?\d+(\.\d+)?\s*$/.test(def.min) ? Number(def.min) : undefined;
  const hi = def.max && /^\s*-?\d+(\.\d+)?\s*$/.test(def.max) ? Number(def.max) : undefined;
  return (
    <input
      type="number"
      min={lo}
      max={hi}
      placeholder={rangeText(def)}
      value={value === undefined ? "" : String(value)}
      onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))}
    />
  );
}

/** 数值字段的范围（下限～上限，只认写死的数）；没有时是空。带可选值的字段下拉里已经列出来了，不再显示。 */
export function rangeText(def: { kind?: string; min?: string | null; max?: string | null; choices?: readonly string[] | null }): string {
  if (def.kind !== "number" || (def.choices && def.choices.length)) return "";
  const num = (x: string | null | undefined) => (x && /^\s*-?\d+(\.\d+)?\s*$/.test(x) ? x.trim() : "");
  const lo = num(def.min);
  const hi = num(def.max);
  if (!lo && !hi) return "";
  return `${lo || "…"} ～ ${hi || "…"}`;
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
  simple = false,
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
  /** 建卡的玩家用：技能设置和脚本收在“让引擎自动执行”里，默认收起 */
  simple?: boolean;
}) {
  const { t } = useI18n();
  const fields = group.fields ?? [];
  const v = useCallback((f: string) => validate(f, group.name), [validate, group.name]);
  const vDice = useCallback((f: string) => validate(f, group.name, "dice"), [validate, group.name]);
  // 设置和脚本可以互相引用名字：校验一边时带上另一边
  const vScript = useCallback((f: string) => validate(f, group.name, "script", entry.config ?? ""), [validate, group.name, entry.config]);
  const vConfig = useCallback((f: string) => validate(f, group.name, "config", entry.script ?? ""), [validate, group.name, entry.script]);
  const idField = (
    <label>
      {t("rules.gt.id")}
      <small className="sk-field-desc">{t("rules.gt.id_hint")}</small>
      <input value={entry.id ?? ""} placeholder={t("rules.gt.id_ph")} onChange={(e) => onChange({ ...entry, id: e.target.value.trim() })} />
    </label>
  );
  return (
    <div className="sk-entry">
      {mover && <div className="sk-row sk-row-end">{mover}</div>}
      <label>
        {t("character.entry_name")}
        <input value={entry.name} onChange={(e) => onChange({ ...entry, name: e.target.value })} />
      </label>
      {!simple && idField}
      <label>
        {t("character.entry_description")}
        <textarea rows={2} value={entry.description} onChange={(e) => onChange({ ...entry, description: e.target.value })} />
      </label>
      {fields.map((f) => (
        <label key={f.name}>
          {fieldLabel(f, t("character.unnamed_field"))}
          {rangeText(f) && <span className="sk-range"> {t("character.range", { range: rangeText(f) })}</span>}
          {f.kind === "formula" && <small className="sk-field-desc">{t("character.formula_field")}</small>}
          <Described text={f.description} />
          <FieldInput def={f} value={entry.fields[f.name]} validateFormula={vDice} onChange={(val) => onChange({ ...entry, fields: { ...entry.fields, [f.name]: val } })} />
        </label>
      ))}
      {group.effects !== false && <EffectsEditor effects={entry.effects} derived={derived} validate={v} withPriority={withPriority} onChange={(effects) => onChange({ ...entry, effects })} />}
      {group.effects !== false &&
        (simple ? (
          <details className="sk-engine" open={Boolean((entry.config ?? "").trim() || (entry.script ?? "").trim())}>
            <summary>{t("character.engine_rules")}</summary>
            <p className="sk-hint">{t("character.engine_rules_hint")}</p>
            {idField}
            <ConfigEditor config={entry.config || fillConfig("", group, t)} validate={vConfig} onChange={(config) => onChange({ ...entry, config })} />
            <ScriptEditor script={entry.script ?? ""} validate={vScript} onChange={(script) => onChange({ ...entry, script })} />
          </details>
        ) : (
          <>
            <ConfigEditor config={entry.config || fillConfig("", group, t)} validate={vConfig} onChange={(config) => onChange({ ...entry, config })} />
            <ScriptEditor script={entry.script ?? ""} validate={vScript} onChange={(script) => onChange({ ...entry, script })} />
          </>
        ))}
      {group.effects !== false && <UsesList group={group} uses={entry.uses ?? []} base={entry.config ?? ""} validate={validate} onChange={(uses) => onChange({ ...entry, uses })} />}
      {onRemove && (
        <button type="button" className="sk-link" onClick={onRemove}>
          {t("character.remove_entry")}
        </button>
      )}
    </div>
  );
}

/** 条目的几种用途（例如一件装备的几种用法）：各有自己的设置和脚本，设置没写的项沿用条目的。
 * 可以从分组的用途模板里选一个照抄。只写说明的用途由 KP 按说明裁定。 */
function UsesList({ group, uses, base, validate, onChange }: { group: GroupDef; uses: Use[]; base: string; validate: (f: string, inEntry: string, scope?: "dice" | "script" | "config", other?: string) => Promise<{ problems: { code: string }[]; names: string[] }>; onChange: (u: Use[]) => void }) {
  const { t } = useI18n();
  const templates = group.use_templates ?? [];
  const set = (j: number, u: Use) => onChange(uses.map((x, k) => (k === j ? u : x)));
  return (
    <div className="sk-effects">
      <strong>{t("rules.uses.title")}</strong>
      <p className="sk-hint">{t("character.uses_hint")}</p>
      {uses.map((u, j) => (
        <div key={j} className="sk-use">
          <div className="sk-row">
            <input placeholder={t("rules.uses.name")} value={u.name} onChange={(e) => set(j, { ...u, name: e.target.value })} />
            <Mover index={j} count={uses.length} onMove={(from, to) => onChange(moved(uses, from, to))} />
            <button type="button" className="sk-link" onClick={() => onChange(uses.filter((_, k) => k !== j))}>
              {t("common.remove")}
            </button>
          </div>
          <textarea rows={2} placeholder={t("rules.uses.description")} value={u.description ?? ""} onChange={(e) => set(j, { ...u, description: e.target.value })} />
          <ConfigEditor config={u.config ?? ""} validate={(f) => validate(f, group.name, "config", u.script ?? "")} onChange={(config) => set(j, { ...u, config })} />
          <ScriptEditor script={u.script ?? ""} validate={(f) => validate(f, group.name, "script", mergeConfig(base, u.config ?? ""))} onChange={(script) => set(j, { ...u, script })} />
          {!(u.script ?? "").trim() && !(u.config ?? "").trim() && <p className="sk-hint">{t("rules.uses.kp_rules")}</p>}
        </div>
      ))}
      <div className="sk-row">
        <button type="button" onClick={() => onChange([...uses, { name: "", description: "", config: "", script: "" }])}>
          {t("rules.uses.add")}
        </button>
        {templates.length > 0 && (
          <select value="" onChange={(e) => e.target.value !== "" && onChange([...uses, { ...templates[Number(e.target.value)]! }])}>
            <option value="">{t("character.use_from_template")}</option>
            {templates.map((u, k) => (
              <option key={k} value={String(k)}>
                {u.name}
              </option>
            ))}
          </select>
        )}
      </div>
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
      <Hint text={t("config.hint")} />
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
      <Hint text={t("script.hint")} />
    </div>
  );
}
