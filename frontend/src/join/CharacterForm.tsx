import { useCallback, useEffect, useMemo, useState } from "react";
import { api, call, type Schemas } from "../api/client";
import { useI18n } from "../i18n";
import { ErrorBox, FormulaInput } from "../ui/components";

type Template = Schemas["EntityTemplate"];
type FieldDef = Schemas["FieldDef"];
type GroupDef = Schemas["GroupDef"];
type Effect = { description: string; target: string | null; op: "add" | "mul" | null; value: string | null };
type Shape = { kind: "capsule" | "box" | "sphere" | "cone"; length?: number | null; width?: number | null; height?: number | null; radius?: number | null; angle?: number | null };
type Entry = { name: string; description: string; fields: Record<string, string | number>; effects: Effect[]; shape: Shape | null };
export type SheetDraft = { name: string; fields: Record<string, string | number>; groups: Record<string, Entry[]> };
export type Submission = { template: string; sheet: SheetDraft };

function emptySheet(): SheetDraft {
  return { name: "", fields: {}, groups: {} };
}

/** 建角时要创建的实体：按规则包的 player_entities，每个模板先放最少数量。 */
export function initialSubmissions(playerEntities: { template: string; min: number; max: number }[]): Submission[] {
  return playerEntities.flatMap((pe) => Array.from({ length: Math.max(pe.min, 1) }, () => ({ template: pe.template, sheet: emptySheet() })));
}

function FieldInput({ def, value, onChange }: { def: FieldDef; value: string | number | undefined; onChange: (v: string | number) => void }) {
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

function fieldLabel(f: { name: string; label?: string; unit?: string | null }) {
  return `${f.label || f.name}${f.unit ? ` (${f.unit})` : ""}`;
}

function EntryEditor({
  group,
  derived,
  entry,
  onChange,
  onRemove,
  validate,
}: {
  group: GroupDef;
  derived: string[];
  entry: Entry;
  onChange: (e: Entry) => void;
  onRemove: () => void;
  validate: (f: string, inEntry: string) => Promise<{ problems: { code: string }[]; names: string[] }>;
}) {
  const { t } = useI18n();
  const fields = group.fields ?? [];
  const shapes = group.shapes?.allowed ?? [];
  const v = useCallback((f: string) => validate(f, group.name), [validate, group.name]);
  return (
    <div className="sk-entry">
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
          <FieldInput def={f} value={entry.fields[f.name]} onChange={(val) => onChange({ ...entry, fields: { ...entry.fields, [f.name]: val } })} />
        </label>
      ))}
      {group.effects !== false && (
        <div className="sk-effects">
          <strong>{t("character.effects")}</strong>
          {entry.effects.map((ef, i) => (
            <div key={i} className="sk-effect">
              <input placeholder={t("character.effect_description")} value={ef.description} onChange={(e) => onChange({ ...entry, effects: entry.effects.map((x, j) => (j === i ? { ...x, description: e.target.value } : x)) })} />
              <select value={ef.target ?? ""} onChange={(e) => onChange({ ...entry, effects: entry.effects.map((x, j) => (j === i ? { ...x, target: e.target.value || null } : x)) })}>
                <option value="">{t("character.effect_conceptual")}</option>
                {derived.map((d) => (
                  <option key={d} value={d}>
                    {d}
                  </option>
                ))}
              </select>
              {ef.target && (
                <>
                  <select value={ef.op ?? "add"} onChange={(e) => onChange({ ...entry, effects: entry.effects.map((x, j) => (j === i ? { ...x, op: e.target.value as "add" | "mul" } : x)) })}>
                    <option value="add">+</option>
                    <option value="mul">×</option>
                  </select>
                  <FormulaInput value={ef.value ?? ""} validate={v} onChange={(val) => onChange({ ...entry, effects: entry.effects.map((x, j) => (j === i ? { ...x, value: val } : x)) })} />
                </>
              )}
              <button type="button" className="sk-link" onClick={() => onChange({ ...entry, effects: entry.effects.filter((_, j) => j !== i) })}>
                {t("common.remove")}
              </button>
            </div>
          ))}
          <button type="button" onClick={() => onChange({ ...entry, effects: [...entry.effects, { description: "", target: null, op: null, value: null }] })}>
            {t("character.add_effect")}
          </button>
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
      <button type="button" className="sk-link" onClick={onRemove}>
        {t("character.remove_entry")}
      </button>
    </div>
  );
}

/** 一张角色卡：按模板生成表单，实时试算推导值。 */
export function SheetEditor({ template, value, onChange }: { template: Template; value: SheetDraft; onChange: (s: SheetDraft) => void }) {
  const { t } = useI18n();
  const [preview, setPreview] = useState<Schemas["PreviewOut"] | null>(null);
  const fields = (template.fields ?? []).filter((f) => f.cls !== "runtime");
  const derived = (template.derived ?? []).map((d) => d.name);
  const validate = useCallback(
    (formula: string, inEntry: string) =>
      call(api.POST("/api/formula/validate", { body: { formula, template: template.name, in_entry: inEntry } })),
    [template.name],
  );
  const body = useMemo(() => JSON.stringify(value), [value]);
  useEffect(() => {
    const id = window.setTimeout(() => {
      call(api.POST("/api/character/preview", { body: { template: template.name, sheet: JSON.parse(body) } }))
        .then(setPreview)
        .catch(() => setPreview(null));
    }, 500);
    return () => window.clearTimeout(id);
  }, [body, template.name]);
  return (
    <div className="sk-sheet-editor">
      <label>
        {t("character.name")}
        <input value={value.name} onChange={(e) => onChange({ ...value, name: e.target.value })} />
      </label>
      {fields.map((f) => (
        <label key={f.name}>
          {fieldLabel(f)}
          {f.name === template.appearance_field && <small> {t("character.appearance_hint")}</small>}
          <FieldInput def={f} value={value.fields[f.name]} onChange={(v) => onChange({ ...value, fields: { ...value.fields, [f.name]: v } })} />
        </label>
      ))}
      {(template.groups ?? []).map((g) => {
        const entries = value.groups[g.name] ?? [];
        const setEntries = (es: Entry[]) => onChange({ ...value, groups: { ...value.groups, [g.name]: es } });
        return (
          <fieldset key={g.name}>
            <legend>{g.label || g.name}</legend>
            {entries.map((en, i) => (
              <EntryEditor
                key={i}
                group={g}
                derived={derived}
                entry={en}
                validate={validate}
                onChange={(e) => setEntries(entries.map((x, j) => (j === i ? e : x)))}
                onRemove={() => setEntries(entries.filter((_, j) => j !== i))}
              />
            ))}
            {(g.max_count === null || g.max_count === undefined || entries.length < g.max_count) && (
              <button type="button" onClick={() => setEntries([...entries, { name: "", description: "", fields: {}, effects: [], shape: null }])}>
                {t("character.add_entry")}
              </button>
            )}
          </fieldset>
        );
      })}
      {preview && (
        <div className="sk-preview">
          <strong>{t("character.derived")}</strong>
          <ul>
            {preview.derived.map((d) => (
              <li key={d.name}>
                {d.name}: {Math.round(d.value * 100) / 100}
              </li>
            ))}
          </ul>
          {preview.problems.length > 0 && (
            <ul className="sk-problems">
              {preview.problems.map((p, i) => (
                <li key={i}>
                  {p.code} {p.path}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

export function CharacterForm({
  templates,
  playerEntities,
  onSubmitted,
}: {
  templates: Template[];
  playerEntities: { template: string; min: number; max: number }[];
  onSubmitted: () => void;
}) {
  const { t } = useI18n();
  const [subs, setSubs] = useState<Submission[]>(() => initialSubmissions(playerEntities));
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const clean = subs.map((s) => ({
        template: s.template,
        sheet: {
          ...s.sheet,
          fields: Object.fromEntries(Object.entries(s.sheet.fields).filter(([, v]) => v !== "")),
          groups: Object.fromEntries(
            Object.entries(s.sheet.groups).map(([g, es]) => [
              g,
              es.map((e) => ({ ...e, fields: Object.fromEntries(Object.entries(e.fields).filter(([, v]) => v !== "")) })),
            ]),
          ),
        },
      }));
      await call(api.POST("/api/character", { body: { sheets: clean as never } }));
      onSubmitted();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div>
      {playerEntities.map((pe) => {
        const tpl = templates.find((x) => x.name === pe.template);
        if (!tpl) return null;
        const mine = subs.map((s, i) => [s, i] as const).filter(([s]) => s.template === pe.template);
        return (
          <div key={pe.template} className="sk-card">
            <h3>
              {tpl.label || tpl.name} ({pe.min}–{pe.max})
            </h3>
            {mine.map(([s, i]) => (
              <div key={i}>
                <SheetEditor template={tpl} value={s.sheet} onChange={(sheet) => setSubs(subs.map((x, j) => (j === i ? { ...x, sheet } : x)))} />
                {mine.length > pe.min && (
                  <button type="button" className="sk-link" onClick={() => setSubs(subs.filter((_, j) => j !== i))}>
                    {t("common.remove")}
                  </button>
                )}
              </div>
            ))}
            {mine.length < pe.max && (
              <button type="button" onClick={() => setSubs([...subs, { template: pe.template, sheet: emptySheet() }])}>
                {t("character.add_entity")}
              </button>
            )}
          </div>
        );
      })}
      <ErrorBox error={error} />
      <button className="sk-primary" disabled={busy} onClick={() => void submit()}>
        {t("character.submit")}
      </button>
    </div>
  );
}
