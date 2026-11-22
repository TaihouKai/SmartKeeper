import { useCallback, useEffect, useState } from "react";
import { api, call, type Schemas } from "../api/client";
import { useI18n } from "../i18n";
import { ErrorBox, FormulaInput, Section } from "../ui/components";
import { useAction, usePoll } from "../ui/hooks";

type Pack = Schemas["RulePack"];
type Template = Schemas["EntityTemplate"];
type Field = Schemas["FieldDef"];
type Group = Schemas["GroupDef"];

export const REQUIRED_DERIVED = ["perception_radius", "concealment", "move_speed"];

export function blankPack(): Pack {
  return {
    world: { name: "", description: "", canon: "", reference_sites: [] },
    templates: [blankTemplate("character")],
    player_entities: [{ template: "character", min: 1, max: 1 }],
    formulas: [],
    tables: [],
    checks: [],
    rules_text: "",
    samples: [],
  };
}

function blankTemplate(name: string): Template {
  return {
    name,
    label: "",
    appearance_field: "appearance",
    fields: [{ name: "appearance", label: "", kind: "text", cls: "player", required: true, hidden: false, choices: [] }],
    groups: [],
    derived: REQUIRED_DERIVED.map((n) => ({ name: n, label: "", formula: n === "concealment" ? "1" : "", hidden: false })),
  };
}

function blankField(): Field {
  return { name: "", label: "", kind: "number", cls: "player", required: true, hidden: false, choices: [] };
}

type Validate = (formula: string, template: string | null, inEntry?: string) => Promise<{ problems: { code: string }[]; names: string[] }>;

function useListEdit<T>(list: T[], set: (l: T[]) => void) {
  return {
    update: (i: number, v: T) => set(list.map((x, j) => (j === i ? v : x))),
    remove: (i: number) => set(list.filter((_, j) => j !== i)),
    add: (v: T) => set([...list, v]),
  };
}

function FieldsTable({ fields, onChange, validate, template, appearance }: { fields: Field[]; onChange: (f: Field[]) => void; validate: Validate; template: string; appearance?: string }) {
  const { t } = useI18n();
  const ed = useListEdit(fields, onChange);
  const v = useCallback((f: string) => validate(f, template), [validate, template]);
  return (
    <div className="sk-scroll">
      <table className="sk-table">
        <thead>
          <tr>
            <th>{t("rules.f.name")}</th>
            <th>{t("rules.f.label")}</th>
            <th>{t("rules.f.kind")}</th>
            <th>{t("rules.f.cls")}</th>
            <th>{t("rules.f.unit")}</th>
            <th>{t("rules.f.min")}</th>
            <th>{t("rules.f.max")}</th>
            <th>{t("rules.f.initial")}</th>
            <th>{t("rules.f.choices")}</th>
            <th>{t("rules.f.required")}</th>
            <th>{t("rules.f.hidden")}</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {fields.map((f, i) => (
            <tr key={i}>
              <td>
                <input value={f.name} placeholder={t("rules.ph.field_name")} onChange={(e) => ed.update(i, { ...f, name: e.target.value })} />
                {appearance && f.name === appearance && <div className="sk-badge-req">{t("rules.appearance_badge")}</div>}
              </td>
              <td><input value={f.label ?? ""} placeholder={t("rules.ph.field_label")} onChange={(e) => ed.update(i, { ...f, label: e.target.value })} /></td>
              <td>
                <select value={f.kind} onChange={(e) => ed.update(i, { ...f, kind: e.target.value as Field["kind"] })}>
                  <option value="number">{t("rules.kind.number")}</option>
                  <option value="text">{t("rules.kind.text")}</option>
                  <option value="resource">{t("rules.kind.resource")}</option>
                </select>
              </td>
              <td>
                <select value={f.cls ?? "player"} onChange={(e) => ed.update(i, { ...f, cls: e.target.value as Field["cls"] })}>
                  <option value="player">{t("rules.cls.player")}</option>
                  <option value="runtime">{t("rules.cls.runtime")}</option>
                </select>
              </td>
              <td><input value={f.unit ?? ""} onChange={(e) => ed.update(i, { ...f, unit: e.target.value || null })} /></td>
              <td><FormulaInput value={f.min ?? ""} validate={v} onChange={(x) => ed.update(i, { ...f, min: x || null })} /></td>
              <td><FormulaInput value={f.max ?? ""} validate={v} placeholder={f.kind === "resource" ? t("rules.ph.max_resource") : ""} onChange={(x) => ed.update(i, { ...f, max: x || null })} /></td>
              <td><FormulaInput value={f.initial ?? ""} validate={v} placeholder={f.cls === "runtime" ? t("rules.ph.initial") : ""} onChange={(x) => ed.update(i, { ...f, initial: x || null })} /></td>
              <td><input value={(f.choices ?? []).join("|")} onChange={(e) => ed.update(i, { ...f, choices: e.target.value ? e.target.value.split("|") : [] })} /></td>
              <td><input type="checkbox" checked={f.required ?? true} onChange={(e) => ed.update(i, { ...f, required: e.target.checked })} /></td>
              <td><input type="checkbox" checked={f.hidden ?? false} onChange={(e) => ed.update(i, { ...f, hidden: e.target.checked })} /></td>
              <td><button className="sk-link" onClick={() => ed.remove(i)}>{t("common.remove")}</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      <button onClick={() => ed.add(blankField())}>{t("rules.add_field")}</button>
    </div>
  );
}

function TemplateEditor({ tpl, onChange, onRemove, validate }: { tpl: Template; onChange: (t: Template) => void; onRemove: () => void; validate: Validate }) {
  const { t } = useI18n();
  const groups = tpl.groups ?? [];
  const derived = tpl.derived ?? [];
  const ged = useListEdit(groups, (g) => onChange({ ...tpl, groups: g }));
  const ded = useListEdit(derived, (d) => onChange({ ...tpl, derived: d }));
  const v = useCallback((f: string) => validate(f, tpl.name), [validate, tpl.name]);
  return (
    <fieldset className="sk-card">
      <legend>{tpl.label || tpl.name}</legend>
      <p className="sk-hint">{t("rules.template_hint")}</p>
      <div className="sk-row">
        <label>{t("rules.t.name")}<input value={tpl.name} placeholder={t("rules.ph.template_name")} onChange={(e) => onChange({ ...tpl, name: e.target.value })} /></label>
        <label>{t("rules.t.label")}<input value={tpl.label ?? ""} placeholder={t("rules.ph.template_label")} onChange={(e) => onChange({ ...tpl, label: e.target.value })} /></label>
        <label>
          {t("rules.t.appearance")}
          <select value={tpl.appearance_field ?? "appearance"} onChange={(e) => onChange({ ...tpl, appearance_field: e.target.value })}>
            {(tpl.fields ?? []).filter((f) => f.kind === "text").map((f) => <option key={f.name} value={f.name}>{f.name}</option>)}
          </select>
        </label>
        <button className="sk-link" onClick={onRemove}>{t("rules.remove_template")}</button>
      </div>
      <h4>{t("rules.fields")}</h4>
      <p className="sk-hint">{t("rules.fields_hint")}</p>
      <FieldsTable fields={tpl.fields ?? []} onChange={(f) => onChange({ ...tpl, fields: f })} validate={validate} template={tpl.name} appearance={tpl.appearance_field ?? "appearance"} />
      <h4>{t("rules.derived")}</h4>
      <p className="sk-hint">{t("rules.derived_hint")}</p>
      <div className="sk-derived-row sk-derived-head">
        <span>{t("rules.d.name")}</span>
        <span>{t("rules.d.label")}</span>
        <span>{t("rules.d.formula")}</span>
        <span>{t("rules.d.unit")}</span>
        <span />
      </div>
      {derived.map((d, i) => {
        const required = REQUIRED_DERIVED.includes(d.name);
        return (
          <div key={i}>
            <div className="sk-derived-row">
              <input value={d.name} disabled={required} placeholder={t("rules.ph.derived_name")} onChange={(e) => ded.update(i, { ...d, name: e.target.value })} />
              <input value={d.label ?? ""} placeholder={t("rules.ph.derived_label")} onChange={(e) => ded.update(i, { ...d, label: e.target.value })} />
              <FormulaInput value={d.formula} validate={v} placeholder={required ? t(`rules.ph.formula_${d.name}`) : t("rules.ph.formula")} onChange={(x) => ded.update(i, { ...d, formula: x })} />
              <input className="sk-small" value={d.unit ?? ""} placeholder={required ? t(`rules.ph.unit_${d.name}`) : ""} onChange={(e) => ded.update(i, { ...d, unit: e.target.value || null })} />
              {required ? <span className="sk-badge-req">{t("rules.required_badge")}</span> : <button className="sk-link" onClick={() => ded.remove(i)}>{t("common.remove")}</button>}
            </div>
            {required && <div className="sk-hint sk-derived-help">{t(`rules.help.${d.name}`)}</div>}
          </div>
        );
      })}
      <button onClick={() => ded.add({ name: "", label: "", formula: "", hidden: false })}>{t("rules.add_derived")}</button>
      <h4>{t("rules.groups")}</h4>
      {groups.map((g: Group, i) => (
        <div key={i} className="sk-card">
          <div className="sk-row">
            <label>{t("rules.t.name")}<input value={g.name} onChange={(e) => ged.update(i, { ...g, name: e.target.value })} /></label>
            <label>{t("rules.t.label")}<input value={g.label ?? ""} onChange={(e) => ged.update(i, { ...g, label: e.target.value })} /></label>
            <label>{t("rules.g.min")}<input type="number" value={g.min_count ?? 0} onChange={(e) => ged.update(i, { ...g, min_count: Number(e.target.value) })} /></label>
            <label>{t("rules.g.max")}<input type="number" value={g.max_count ?? ""} onChange={(e) => ged.update(i, { ...g, max_count: e.target.value === "" ? null : Number(e.target.value) })} /></label>
            <label className="sk-inline"><input type="checkbox" checked={g.effects ?? true} onChange={(e) => ged.update(i, { ...g, effects: e.target.checked })} /> {t("rules.g.effects")}</label>
            <label>
              {t("rules.g.shapes")}
              <input value={(g.shapes?.allowed ?? []).join("|")} onChange={(e) => ged.update(i, { ...g, shapes: { allowed: (e.target.value ? e.target.value.split("|") : []) as never } })} />
            </label>
            <button className="sk-link" onClick={() => ged.remove(i)}>{t("common.remove")}</button>
          </div>
          <FieldsTable fields={g.fields ?? []} onChange={(f) => ged.update(i, { ...g, fields: f })} validate={validate} template={tpl.name} />
        </div>
      ))}
      <button onClick={() => ged.add({ name: "", label: "", fields: [], min_count: 0, max_count: null, effects: true, shapes: { allowed: [] }, hidden: false })}>{t("rules.add_group")}</button>
    </fieldset>
  );
}

function PackEditor({ pack, onChange, validate }: { pack: Pack; onChange: (p: Pack) => void; validate: Validate }) {
  const { t } = useI18n();
  const ted = useListEdit(pack.templates, (x) => onChange({ ...pack, templates: x }));
  const ped = useListEdit(pack.player_entities, (x) => onChange({ ...pack, player_entities: x }));
  const fed = useListEdit(pack.formulas ?? [], (x) => onChange({ ...pack, formulas: x }));
  const tbl = useListEdit(pack.tables ?? [], (x) => onChange({ ...pack, tables: x }));
  const ced = useListEdit(pack.checks ?? [], (x) => onChange({ ...pack, checks: x }));
  const sed = useListEdit(pack.samples ?? [], (x) => onChange({ ...pack, samples: x }));
  const vNone = useCallback((f: string) => validate(f, null), [validate]);
  const w = pack.world;
  return (
    <div>
      <h3>{t("rules.world")}</h3>
      <label>{t("rules.w.name")}<input value={w.name} onChange={(e) => onChange({ ...pack, world: { ...w, name: e.target.value } })} /></label>
      <label>{t("rules.w.canon")}<input value={w.canon ?? ""} onChange={(e) => onChange({ ...pack, world: { ...w, canon: e.target.value } })} /></label>
      <label>{t("rules.w.description")}<textarea rows={3} value={w.description ?? ""} onChange={(e) => onChange({ ...pack, world: { ...w, description: e.target.value } })} /></label>
      <label>{t("rules.w.sites")}<textarea rows={2} value={(w.reference_sites ?? []).join("\n")} onChange={(e) => onChange({ ...pack, world: { ...w, reference_sites: e.target.value.split("\n").map((x) => x.trim()).filter(Boolean) } })} /></label>

      <h3>{t("rules.templates")}</h3>
      {pack.templates.map((tp, i) => (
        <TemplateEditor key={i} tpl={tp} validate={validate} onChange={(x) => ted.update(i, x)} onRemove={() => ted.remove(i)} />
      ))}
      <button onClick={() => ted.add(blankTemplate(`template_${pack.templates.length + 1}`))}>{t("rules.add_template")}</button>

      <h3>{t("rules.player_entities")}</h3>
      {pack.player_entities.map((pe, i) => (
        <div key={i} className="sk-row">
          <select value={pe.template} onChange={(e) => ped.update(i, { ...pe, template: e.target.value })}>
            {pack.templates.map((tp) => <option key={tp.name} value={tp.name}>{tp.name}</option>)}
          </select>
          <input type="number" value={pe.min ?? 1} onChange={(e) => ped.update(i, { ...pe, min: Number(e.target.value) })} />
          <input type="number" value={pe.max ?? 1} onChange={(e) => ped.update(i, { ...pe, max: Number(e.target.value) })} />
          <button className="sk-link" onClick={() => ped.remove(i)}>{t("common.remove")}</button>
        </div>
      ))}
      <button onClick={() => ped.add({ template: pack.templates[0]?.name ?? "", min: 1, max: 1 })}>{t("common.add")}</button>

      <h3>{t("rules.formulas")}</h3>
      {(pack.formulas ?? []).map((f, i) => (
        <div key={i} className="sk-row">
          <input value={f.name} onChange={(e) => fed.update(i, { ...f, name: e.target.value })} />
          <FormulaInput value={f.formula} validate={vNone} onChange={(x) => fed.update(i, { ...f, formula: x })} />
          <button className="sk-link" onClick={() => fed.remove(i)}>{t("common.remove")}</button>
        </div>
      ))}
      <button onClick={() => fed.add({ name: "", formula: "", label: "" })}>{t("common.add")}</button>

      <h3>{t("rules.tables")}</h3>
      <p className="sk-hint">{t("rules.tables_hint")}</p>
      {(pack.tables ?? []).map((tb, i) => (
        <div key={i} className="sk-card">
          <div className="sk-row">
            <input value={tb.name} onChange={(e) => tbl.update(i, { ...tb, name: e.target.value })} />
            <select value={tb.kind ?? "range"} onChange={(e) => tbl.update(i, { ...tb, kind: e.target.value as "range" | "exact" })}>
              <option value="range">{t("rules.table.range")}</option>
              <option value="exact">{t("rules.table.exact")}</option>
            </select>
            <button className="sk-link" onClick={() => tbl.remove(i)}>{t("common.remove")}</button>
          </div>
          <textarea
            rows={4}
            value={tb.rows.map(([k, v]) => `${k},${v}`).join("\n")}
            onChange={(e) =>
              tbl.update(i, {
                ...tb,
                rows: e.target.value.split("\n").filter((l) => l.includes(",")).map((l) => {
                  const [k = "", v = "0"] = l.split(",");
                  const num = Number(k);
                  return [k.trim() !== "" && !Number.isNaN(num) ? num : k.trim(), Number(v)] as [number | string, number];
                }),
              })
            }
          />
        </div>
      ))}
      <button onClick={() => tbl.add({ name: "", kind: "range", rows: [] })}>{t("common.add")}</button>

      <h3>{t("rules.checks")}</h3>
      {(pack.checks ?? []).map((c, i) => (
        <div key={i} className="sk-card">
          <div className="sk-row">
            <label>{t("rules.t.name")}<input value={c.name} onChange={(e) => ced.update(i, { ...c, name: e.target.value })} /></label>
            <label>{t("rules.c.dice")}<input value={c.dice} onChange={(e) => ced.update(i, { ...c, dice: e.target.value })} /></label>
            <label>{t("rules.c.target")}<FormulaInput value={c.target ?? "0"} validate={vNone} onChange={(x) => ced.update(i, { ...c, target: x })} /></label>
            <button className="sk-link" onClick={() => ced.remove(i)}>{t("common.remove")}</button>
          </div>
          {c.levels.map((lv, j) => (
            <div key={j} className="sk-row">
              <input value={lv.name} onChange={(e) => ced.update(i, { ...c, levels: c.levels.map((x, k) => (k === j ? { ...x, name: e.target.value } : x)) })} />
              <FormulaInput value={lv.condition} validate={vNone} onChange={(x) => ced.update(i, { ...c, levels: c.levels.map((y, k) => (k === j ? { ...y, condition: x } : y)) })} />
              <button className="sk-link" onClick={() => ced.update(i, { ...c, levels: c.levels.filter((_, k) => k !== j) })}>{t("common.remove")}</button>
            </div>
          ))}
          <button onClick={() => ced.update(i, { ...c, levels: [...c.levels, { name: "", condition: "" }] })}>{t("rules.add_level")}</button>
          <p className="sk-hint">{t("rules.levels_hint")}</p>
        </div>
      ))}
      <button onClick={() => ced.add({ name: "", label: "", dice: "1d100", target: "0", levels: [] })}>{t("common.add")}</button>

      <h3>{t("rules.rules_text")}</h3>
      <textarea rows={8} value={pack.rules_text ?? ""} onChange={(e) => onChange({ ...pack, rules_text: e.target.value })} />

      <h3>{t("rules.samples")}</h3>
      <p className="sk-hint">{t("rules.samples_hint")}</p>
      {(pack.samples ?? []).map((s, i) => (
        <SampleEditor key={i} sample={s} templates={pack.templates.map((x) => x.name)} onChange={(x) => sed.update(i, x)} onRemove={() => sed.remove(i)} />
      ))}
      <button onClick={() => sed.add({ name: "", template: pack.templates[0]?.name ?? "", sheet: { name: "sample", fields: {} }, expected: {} })}>{t("common.add")}</button>
    </div>
  );
}

function SampleEditor({ sample, templates, onChange, onRemove }: { sample: Schemas["SampleSheet"]; templates: string[]; onChange: (s: Schemas["SampleSheet"]) => void; onRemove: () => void }) {
  const { t } = useI18n();
  const [sheetText, setSheetText] = useState(() => JSON.stringify(sample.sheet, null, 1));
  const [bad, setBad] = useState(false);
  return (
    <div className="sk-card">
      <div className="sk-row">
        <input value={sample.name} onChange={(e) => onChange({ ...sample, name: e.target.value })} />
        <select value={sample.template} onChange={(e) => onChange({ ...sample, template: e.target.value })}>
          {templates.map((x) => <option key={x} value={x}>{x}</option>)}
        </select>
        <button className="sk-link" onClick={onRemove}>{t("common.remove")}</button>
      </div>
      <label>
        {t("rules.sample_sheet")}
        <textarea
          rows={6}
          className={bad ? "invalid" : ""}
          value={sheetText}
          onChange={(e) => {
            setSheetText(e.target.value);
            try {
              onChange({ ...sample, sheet: JSON.parse(e.target.value) });
              setBad(false);
            } catch {
              setBad(true);
            }
          }}
        />
      </label>
      <label>
        {t("rules.sample_expected")}
        <textarea
          rows={3}
          value={Object.entries(sample.expected).map(([k, v]) => `${k}=${v}`).join("\n")}
          onChange={(e) =>
            onChange({
              ...sample,
              expected: Object.fromEntries(
                e.target.value.split("\n").filter((l) => l.includes("=")).map((l) => {
                  const [k = "", v = "0"] = l.split("=");
                  return [k.trim(), Number(v)];
                }),
              ),
            })
          }
        />
      </label>
    </div>
  );
}

function TryPanel({ pack }: { pack: Pack }) {
  const { t } = useI18n();
  const [template, setTemplate] = useState(pack.templates[0]?.name ?? "");
  const [sheet, setSheet] = useState(() => JSON.stringify(pack.samples?.[0]?.sheet ?? { name: "x", fields: {} }, null, 1));
  const act = useAction();
  const [out, setOut] = useState<Schemas["TryOut"] | null>(null);
  return (
    <div className="sk-card">
      <h3>{t("rules.try")}</h3>
      <select value={template} onChange={(e) => setTemplate(e.target.value)}>
        {pack.templates.map((x) => <option key={x.name} value={x.name}>{x.name}</option>)}
      </select>
      <textarea rows={6} value={sheet} onChange={(e) => setSheet(e.target.value)} />
      <button onClick={() => void act.run(async () => setOut(await call(api.POST("/api/admin/rulepacks/try", { body: { pack, template, sheet: JSON.parse(sheet) } }))))}>
        {t("rules.try_run")}
      </button>
      <ErrorBox error={act.error} />
      {out && (
        <ul>
          {out.derived.map((d) => <li key={d.name}>{d.name} = {d.value} ({d.base}{d.modifiers?.length ? `; ${d.modifiers.join(", ")}` : ""})</li>)}
          {out.problems.map((p, i) => <li key={i} className="sk-invalid">{p.code} {p.path}</li>)}
        </ul>
      )}
    </div>
  );
}

/** “规则”面板：新建和编辑规则包、试算、版本管理、导入导出。 */
export function RulesPanel() {
  const { t } = useI18n();
  const packs = usePoll(() => call(api.GET("/api/admin/rulepacks")), 600_000);
  const [current, setCurrent] = useState<{ id: string | null; version: number | null }>({ id: null, version: null });
  const [pack, setPack] = useState<Pack>(blankPack);
  const [problems, setProblems] = useState<Schemas["Problem"][] | null>(null);
  const [checkError, setCheckError] = useState<unknown>(null);
  const act = useAction();
  const validate: Validate = useCallback(
    (formula, template, inEntry) => call(api.POST("/api/admin/rulepacks/formula", { body: { pack, formula, template, in_entry: inEntry ?? null } })),
    [pack],
  );
  useEffect(() => {
    setProblems(null);
    const id = window.setTimeout(() => {
      call(api.POST("/api/admin/rulepacks/validate", { body: { pack } }))
        .then((r) => {
          setProblems(r.problems);
          setCheckError(null);
        })
        .catch((e: unknown) => setCheckError(e));
    }, 600);
    return () => window.clearTimeout(id);
  }, [pack]);

  const open = (id: string, version: number) =>
    void act.run(async () => {
      const v = await call(api.GET("/api/admin/rulepacks/{pack_id}/versions/{version}", { params: { path: { pack_id: id, version } } }));
      setPack(v.pack);
      setCurrent({ id, version });
    });
  const save = () =>
    void act.run(async () => {
      let id = current.id;
      if (!id) id = (await call(api.POST("/api/admin/rulepacks", { body: { name: pack.world.name || "rulepack" } }))).pack_id;
      const v = await call(api.POST("/api/admin/rulepacks/{pack_id}/versions", { params: { path: { pack_id: id } }, body: { pack } }));
      setCurrent({ id, version: v.version });
      void packs.refresh();
    });
  const importFile = (file: File) =>
    void act.run(async () => {
      const v = await call(api.POST("/api/admin/rulepacks/import", { body: { text: await file.text() } }));
      setPack(v.pack);
      setCurrent({ id: v.pack_id, version: v.version });
      void packs.refresh();
    });
  const remove = (id: string, version: number) =>
    void act.run(async () => {
      await call(api.DELETE("/api/admin/rulepacks/{pack_id}/versions/{version}", { params: { path: { pack_id: id, version } } }));
      void packs.refresh();
    });

  return (
    <Section title={t("admin.panel.rules")}>
      <div className="sk-card">
        <h3>{t("rules.packs")}</h3>
        <ul>
          {(packs.data ?? []).map((p) => (
            <li key={p.pack_id}>
              <strong>{p.name}</strong>{" "}
              {p.versions.map((v) => (
                <span key={v} className="sk-chip">
                  <button className="sk-link" onClick={() => open(p.pack_id, v)}>v{v}</button>
                  <a href={`/api/admin/rulepacks/${p.pack_id}/versions/${v}/export`}>{t("rules.export")}</a>
                  <button className="sk-link" onClick={() => remove(p.pack_id, v)}>{t("common.remove")}</button>
                </span>
              ))}
            </li>
          ))}
        </ul>
        <div className="sk-row">
          <button onClick={() => { setPack(blankPack()); setCurrent({ id: null, version: null }); }}>{t("rules.new")}</button>
          <label className="sk-inline">
            {t("rules.import")}
            <input type="file" accept=".json,application/json" onChange={(e) => e.target.files?.[0] && importFile(e.target.files[0])} />
          </label>
        </div>
      </div>
      <p className="sk-hint">
        {current.id ? t("rules.editing", { id: current.id, version: String(current.version) }) : t("rules.editing_new")}
      </p>
      <PackEditor pack={pack} onChange={setPack} validate={validate} />
      <TryPanel pack={pack} />
      <div className="sk-sticky">
        {problems === null ? (
          <span className="sk-hint">{t("rules.checking")}</span>
        ) : problems.length > 0 ? (
          <details>
            <summary className="sk-invalid">{t("rules.problems", { n: String(problems.length) })}</summary>
            <ul>{problems.slice(0, 50).map((p, i) => <li key={i}>{p.code} {p.path} {p.params ? JSON.stringify(p.params) : ""}</li>)}</ul>
          </details>
        ) : (
          <span>{t("rules.valid")}</span>
        )}
        <button className="sk-primary" disabled={act.busy || problems === null || problems.length > 0} onClick={save}>
          {t("rules.save_version")}
        </button>
        <ErrorBox error={act.error ?? checkError} />
      </div>
    </Section>
  );
}
