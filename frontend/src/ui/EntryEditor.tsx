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
export type PlacementSpec = { radius: string; perceive_multiplier?: string; charges?: string; duration?: string; notify_owner?: boolean };
export type Entry = { name: string; id?: string; description: string; fields: Record<string, string | number | boolean>; effects: Effect[]; shape: Shape | null; placement?: PlacementSpec | null; script?: string; cast_time?: string; cooldown?: string };

type Check = (f: string) => Promise<{ problems: { code: string }[]; names: string[] }>;

export function FieldInput({ def, value, onChange, validateFormula }: { def: FieldDef; value: string | number | boolean | undefined; onChange: (v: string | number | boolean) => void; validateFormula?: Check }) {
  const { t } = useI18n();
  if (def.kind === "param") {
    // 使用时填写（例如这次消耗多少魔力）：建角时不填，行动里说
    return <span className="sk-hint">{t("character.param_field", { min: def.min ?? "-", max: def.max ?? "-" })}</span>;
  }
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
  validate: (f: string, inEntry: string, scope?: "dice" | "script") => Promise<{ problems: { code: string }[]; names: string[] }>;
  /** 玩家写的条目要给效果填计算顺序；规则包的固定条目按定义顺序，不用填 */
  withPriority?: boolean;
  mover?: ReactNode;
}) {
  const { t } = useI18n();
  const fields = group.fields ?? [];
  const shapes = group.shapes?.allowed ?? [];
  const v = useCallback((f: string) => validate(f, group.name), [validate, group.name]);
  const vDice = useCallback((f: string) => validate(f, group.name, "dice"), [validate, group.name]);
  const vScript = useCallback((f: string) => validate(f, group.name, "script"), [validate, group.name]);
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
      {group.timing && (
        <div className="sk-field-extra">
          <label title={t("rules.gt.timing_hint")}>
            {t("rules.gt.cast_time")}
            <FormulaInput value={entry.cast_time ?? ""} validate={v} placeholder={t("rules.gt.instant")} onChange={(x) => onChange({ ...entry, cast_time: x })} />
          </label>
          <label title={t("rules.gt.timing_hint")}>
            {t("rules.gt.cooldown")}
            <FormulaInput value={entry.cooldown ?? ""} validate={v} placeholder={t("rules.gt.no_cd")} onChange={(x) => onChange({ ...entry, cooldown: x })} />
          </label>
        </div>
      )}
      {fields.map((f) => (
        <label key={f.name}>
          {fieldLabel(f, t("character.unnamed_field"))}
          {f.kind === "formula" && <small className="sk-field-desc">{t("character.formula_field")}</small>}
          {f.description && <small className="sk-field-desc">{f.description}</small>}
          <FieldInput def={f} value={entry.fields[f.name]} validateFormula={vDice} onChange={(val) => onChange({ ...entry, fields: { ...entry.fields, [f.name]: val } })} />
        </label>
      ))}
      {group.effects !== false && <EffectsEditor effects={entry.effects} derived={derived} validate={v} withPriority={withPriority} onChange={(effects) => onChange({ ...entry, effects })} />}
      {group.effects !== false && <ScriptEditor script={entry.script ?? ""} validate={vScript} onChange={(script) => onChange({ ...entry, script })} />}
      {shapes.length > 0 && <ShapeEditor allowed={shapes} shape={entry.shape} onChange={(shape) => onChange({ ...entry, shape })} />}
      {group.placements && <PlacementEditor spec={entry.placement ?? null} validate={v} onChange={(placement) => onChange({ ...entry, placement })} />}
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

/** 技能脚本：用这个条目（并且 KP 判定生效）时引擎执行的语句，一行一句。 */
export function ScriptEditor({ script, validate, onChange }: { script: string; validate: Check; onChange: (s: string) => void }) {
  const { t } = useI18n();
  return (
    <div className="sk-effects sk-script">
      <strong>{t("script.title")}</strong>
      <FormulaInput multiline value={script} validate={validate} placeholder={t("script.ph")} onChange={onChange} />
      <p className="sk-hint">{t("script.hint")}</p>
    </div>
  );
}

/** 条目的范围形状（范围攻击、光束等）：种类和尺寸。 */
export function ShapeEditor({ allowed, shape, onChange }: { allowed: string[]; shape: Shape | null; onChange: (s: Shape | null) => void }) {
  const { t } = useI18n();
  return (
    <div className="sk-shape">
      <strong>{t("character.shape")}</strong>
      <select value={shape?.kind ?? ""} onChange={(e) => onChange(e.target.value ? { kind: e.target.value as Shape["kind"] } : null)}>
        <option value="">{t("character.shape_none")}</option>
        {allowed.map((s) => (
          <option key={s} value={s}>
            {t(`shape.${s}`)}
          </option>
        ))}
      </select>
      {shape &&
        (["length", "width", "height", "radius", "angle"] as const).map((k) => (
          <label key={k}>
            {t(`shape.${k}`)}
            <input type="number" value={shape[k] ?? ""} onChange={(e) => onChange({ ...shape, [k]: e.target.value === "" ? null : Number(e.target.value) })} />
          </label>
        ))}
    </div>
  );
}

/** 设置物参数（陷阱、结界等）：勾上“这一条是设置物”后填范围、发现难度、次数、持续时间、是否通知设置者。 */
export function PlacementEditor({ spec, validate, onChange }: { spec: PlacementSpec | null; validate: Check; onChange: (s: PlacementSpec | null) => void }) {
  const { t } = useI18n();
  const set = (patch: Partial<PlacementSpec>) => onChange({ ...(spec ?? { radius: "" }), ...patch });
  return (
    <div className="sk-placement">
      <label className="sk-inline">
        <input type="checkbox" checked={spec !== null} onChange={(e) => onChange(e.target.checked ? { radius: "1", perceive_multiplier: "1", charges: "", duration: "", notify_owner: true } : null)} />{" "}
        <strong>{t("placement.is")}</strong>
      </label>
      {spec && (
        <>
          <div className="sk-field-extra">
            <label>
              {t("placement.radius")}
              <FormulaInput value={spec.radius} validate={validate} placeholder={t("placement.ph.radius")} onChange={(x) => set({ radius: x })} />
            </label>
            <label>
              {t("placement.perceive")}
              <FormulaInput value={spec.perceive_multiplier ?? "1"} validate={validate} placeholder={t("placement.ph.perceive")} onChange={(x) => set({ perceive_multiplier: x })} />
            </label>
            <label>
              {t("placement.charges")}
              <FormulaInput value={spec.charges ?? ""} validate={validate} placeholder={t("placement.ph.unlimited")} onChange={(x) => set({ charges: x })} />
            </label>
            <label>
              {t("placement.duration")}
              <FormulaInput value={spec.duration ?? ""} validate={validate} placeholder={t("placement.ph.forever")} onChange={(x) => set({ duration: x })} />
            </label>
          </div>
          <label className="sk-inline">
            <input type="checkbox" checked={spec.notify_owner ?? true} onChange={(e) => set({ notify_owner: e.target.checked })} /> {t("placement.notify")}
          </label>
          <p className="sk-hint">{t("placement.hint")}</p>
        </>
      )}
    </div>
  );
}
