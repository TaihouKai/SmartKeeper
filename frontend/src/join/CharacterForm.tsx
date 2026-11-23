import { useCallback, useEffect, useMemo, useState } from "react";
import { api, call, type Schemas } from "../api/client";
import { useI18n } from "../i18n";
import { ErrorBox } from "../ui/components";
import { EntryEditor, FieldInput, fieldLabel, type Entry } from "../ui/EntryEditor";

type Template = Schemas["EntityTemplate"];
export type SheetDraft = { name: string; fields: Record<string, string | number>; groups: Record<string, Entry[]> };
export type Submission = { template: string; sheet: SheetDraft };

function emptySheet(): SheetDraft {
  return { name: "", fields: {}, groups: {} };
}

/** 建角时要创建的实体：按规则包的 player_entities，每个模板先放最少数量。 */
export function initialSubmissions(playerEntities: { template: string; min: number; max: number }[]): Submission[] {
  return playerEntities.flatMap((pe) => Array.from({ length: Math.max(pe.min, 1) }, () => ({ template: pe.template, sheet: emptySheet() })));
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
          {f.description && <small className="sk-field-desc">{f.description}</small>}
          <FieldInput def={f} value={value.fields[f.name]} onChange={(v) => onChange({ ...value, fields: { ...value.fields, [f.name]: v } })} />
        </label>
      ))}
      {(template.groups ?? []).map((g) => {
        const entries = value.groups[g.name] ?? [];
        const setEntries = (es: Entry[]) => onChange({ ...value, groups: { ...value.groups, [g.name]: es } });
        return (
          <fieldset key={g.name}>
            <legend>{g.label || g.name}</legend>
            {(preview?.presets?.[g.name] ?? []).length > 0 && (
              <p className="sk-hint">{t("character.fixed_entries", { names: (preview?.presets?.[g.name] ?? []).join("、") })}</p>
            )}
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
