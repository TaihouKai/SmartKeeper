import { useCallback, useEffect, useState, type ReactNode } from "react";
import { api, call, type Schemas } from "../../api/client";
import { useI18n } from "../../i18n";
import { ErrorBox, FormulaInput, Mover, moved } from "../../ui/components";
import { useAction } from "../../ui/hooks";
import { FieldCard, blankField, useListEdit, type Validate } from "../fieldCard";
import { GroupTable } from "../GroupTable";
import { useWorkbench } from "./ctx";
import { FLY_FIELD, HP_FIELD, REQUIRED_DERIVED, type Field, type Group, type Pack, type Template } from "./model";

const SHAPES = ["capsule", "box", "sphere", "cone"] as const;

/** 每一节的标题：上面一行是位置（面包屑），右边放这一节的操作。 */
export function SectionHead({ crumbs, title, hint, actions }: { crumbs?: string[]; title: ReactNode; hint?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="wb-head">
      {crumbs && crumbs.length > 0 && <div className="wb-crumbs">{crumbs.join(" › ")}</div>}
      <div className="wb-head-row">
        <h2>{title}</h2>
        {actions && <div className="wb-head-actions">{actions}</div>}
      </div>
      {hint && <p className="wb-hint">{hint}</p>}
    </header>
  );
}

export function WorldSection({ pack, onChange }: { pack: Pack; onChange: (p: Pack) => void }) {
  const { t } = useI18n();
  const w = pack.world;
  const set = (patch: Partial<Pack["world"]>) => onChange({ ...pack, world: { ...w, ...patch } });
  return (
    <>
      <SectionHead title={t("rules.world")} />
      <div className="wb-form">
        <label>
          {t("rules.w.name")}
          <input value={w.name} onChange={(e) => set({ name: e.target.value })} />
        </label>
        <label>
          {t("rules.w.canon")}
          <input value={w.canon ?? ""} onChange={(e) => set({ canon: e.target.value })} />
        </label>
        <label className="wb-wide">
          {t("rules.w.description")}
          <textarea rows={6} value={w.description ?? ""} onChange={(e) => set({ description: e.target.value })} />
        </label>
        <label className="wb-wide">
          {t("rules.w.sites")}
          <textarea rows={3} value={(w.reference_sites ?? []).join("\n")} onChange={(e) => set({ reference_sites: e.target.value.split("\n").map((x) => x.trim()).filter(Boolean) })} />
        </label>
      </div>
    </>
  );
}

/** 模板：ID、显示名和字段列表。 */
export function FieldsSection({ tpl, onChange, onRemove, validate, mover }: { tpl: Template; onChange: (t: Template) => void; onRemove: () => void; validate: Validate; mover: ReactNode }) {
  const { t } = useI18n();
  const fields = tpl.fields ?? [];
  const ed = useListEdit(fields, (f) => onChange({ ...tpl, fields: f }));
  const v = useCallback((f: string) => validate(f, tpl.name), [validate, tpl.name]);
  const appearance = tpl.appearance_field ?? "appearance";
  return (
    <>
      <SectionHead
        crumbs={[t("rules.templates"), tpl.label || tpl.name]}
        title={t("rules.fields")}
        hint={t("rules.fields_hint")}
        actions={
          <>
            {mover}
            <button className="sk-link wb-danger" onClick={onRemove}>
              {t("rules.remove_template")}
            </button>
          </>
        }
      />
      <div className="wb-panel">
        <div className="wb-form wb-form-3">
          <label>
            {t("rules.t.name")}
            <input value={tpl.name} placeholder={t("rules.ph.template_name")} onChange={(e) => onChange({ ...tpl, name: e.target.value })} />
          </label>
          <label>
            {t("rules.t.label")}
            <input value={tpl.label ?? ""} placeholder={t("rules.ph.template_label")} onChange={(e) => onChange({ ...tpl, label: e.target.value })} />
          </label>
        </div>
        <p className="wb-hint">{t("rules.template_hint")}</p>
      </div>
      {fields.map((f: Field, i) => (
        <FieldCard
          key={i}
          f={f}
          validate={v}
          inGroup={false}
          isAppearance={f.name === appearance}
          isFly={f.name === FLY_FIELD}
          isHp={f.name === HP_FIELD}
          onChange={(x) => ed.update(i, x)}
          onRemove={() => ed.remove(i)}
          mover={<Mover index={i} count={fields.length} onMove={ed.move} />}
        />
      ))}
      <button onClick={() => ed.add(blankField())}>{t("rules.add_field")}</button>
    </>
  );
}

export function DerivedSection({ tpl, onChange, validate, base }: { tpl: Template; onChange: (t: Template) => void; validate: Validate; base: string }) {
  const { t } = useI18n();
  const wb = useWorkbench();
  const derived = tpl.derived ?? [];
  const ded = useListEdit(derived, (d) => onChange({ ...tpl, derived: d }));
  const v = useCallback((f: string) => validate(f, tpl.name), [validate, tpl.name]);
  return (
    <>
      <SectionHead crumbs={[t("rules.templates"), tpl.label || tpl.name]} title={t("rules.derived")} hint={t("rules.derived_hint")} />
      <div className="wb-panel">
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
            <div key={i} className="wb-derived">
              <div className="sk-derived-row">
                <input value={d.name} disabled={required} title={required ? t("rules.locked") : undefined} placeholder={t("rules.ph.derived_name")} onChange={(e) => ded.update(i, { ...d, name: e.target.value })} />
                <input value={d.label ?? ""} placeholder={required ? t(`rules.ph.label_${d.name}`) : t("rules.ph.derived_label")} onChange={(e) => ded.update(i, { ...d, label: e.target.value })} />
                <FormulaInput value={d.formula} validate={v} placeholder={required ? t(`rules.ph.formula_${d.name}`) : t("rules.ph.formula")} onChange={(x) => ded.update(i, { ...d, formula: x })} onExpand={() => wb.open(`${base}.derived[${i}].formula`)} />
                <input className="sk-small" value={d.unit ?? ""} placeholder={required ? t(`rules.ph.unit_${d.name}`) : ""} onChange={(e) => ded.update(i, { ...d, unit: e.target.value || null })} />
                <span className="sk-side-actions">
                  <Mover index={i} count={derived.length} onMove={ded.move} />
                  {required ? <span className="sk-badge-req">{t("rules.required_badge")}</span> : <button className="sk-link" onClick={() => ded.remove(i)}>{t("common.remove")}</button>}
                </span>
              </div>
              {required && <div className="sk-hint sk-derived-help">{t(`rules.help.${d.name}`)}</div>}
            </div>
          );
        })}
        <button onClick={() => ded.add({ name: "", label: "", formula: "", hidden: false })}>{t("rules.add_derived")}</button>
      </div>
    </>
  );
}

/** 一个分组：上面是设置（名字、数量、开关、范围形状），下面是条目表。 */
export function GroupSection({ tpl, g, onChange, onRemove, validate, base, mover }: { tpl: Template; g: Group; onChange: (g: Group) => void; onRemove: () => void; validate: Validate; base: string; mover: ReactNode }) {
  const { t } = useI18n();
  const allowed = g.shapes?.allowed ?? [];
  const [settings, setSettings] = useState(false);
  const flag = (key: "effects" | "hidden" | "placements" | "timing", def: boolean, label: string) => (
    <label className="sk-inline">
      <input type="checkbox" checked={g[key] ?? def} onChange={(e) => onChange({ ...g, [key]: e.target.checked })} /> {label}
    </label>
  );
  return (
    <>
      <SectionHead
        crumbs={[t("rules.templates"), tpl.label || tpl.name, t("rules.groups")]}
        title={g.label || g.name || t("rules.g.untitled")}
        actions={
          <>
            {mover}
            <button className="sk-link wb-danger" onClick={onRemove}>
              {t("common.remove")}
            </button>
          </>
        }
      />
      <div className="wb-panel">
        <div className="wb-form wb-form-4">
          <label>
            {t("rules.g.name")}
            <input value={g.name} placeholder={t("rules.ph.group_name")} onChange={(e) => onChange({ ...g, name: e.target.value })} />
          </label>
          <label>
            {t("rules.g.label")}
            <input value={g.label ?? ""} placeholder={t("rules.ph.group_label")} onChange={(e) => onChange({ ...g, label: e.target.value })} />
          </label>
          <label>
            {t("rules.g.min")}
            <input type="number" min={0} value={g.min_count ?? 0} onChange={(e) => onChange({ ...g, min_count: Number(e.target.value) })} />
          </label>
          <label>
            {t("rules.g.max")}
            <input type="number" min={0} value={g.max_count ?? ""} placeholder={t("rules.ph.group_max")} onChange={(e) => onChange({ ...g, max_count: e.target.value === "" ? null : Number(e.target.value) })} />
          </label>
        </div>
        <button type="button" className="sk-link wb-toggle" aria-expanded={settings} onClick={() => setSettings(!settings)}>
          {settings ? "▾" : "▸"} {t("rules.g.settings")}
        </button>
        {settings && (
          <div className="wb-settings">
            <div className="sk-field-flags">
              {flag("effects", true, t("rules.g.effects"))}
              {flag("hidden", false, t("rules.g.hidden"))}
              {flag("placements", false, t("rules.g.placements"))}
              {flag("timing", false, t("rules.g.timing"))}
            </div>
            <div className="wb-shapes">
              <span className="sk-hint">{t("rules.g.shapes")}</span>
              {SHAPES.map((s) => (
                <label key={s} className="sk-inline">
                  <input
                    type="checkbox"
                    checked={allowed.includes(s)}
                    onChange={(e) => onChange({ ...g, shapes: { allowed: e.target.checked ? SHAPES.filter((x) => x === s || allowed.includes(x)) : allowed.filter((x) => x !== s) } })}
                  />{" "}
                  {t(`shape.${s}`)}
                </label>
              ))}
            </div>
          </div>
        )}
      </div>
      <div className="wb-sub-row">
        <h3 className="wb-sub">{t("rules.gt.title")}</h3>
        <details className="wb-help">
          <summary>{t("rules.how")}</summary>
          <p>{t("rules.gt.hint")}</p>
        </details>
      </div>
      <GroupTable
        g={g}
        onChange={onChange}
        validate={validate}
        template={tpl.name}
        base={base}
        derived={(tpl.derived ?? []).map((d) => d.name)}
        spendTargets={(tpl.fields ?? []).filter((f) => f.kind === "number" || f.kind === "resource").map((f) => f.name)}
      />
    </>
  );
}

export function PlayersSection({ pack, onChange }: { pack: Pack; onChange: (p: Pack) => void }) {
  const { t } = useI18n();
  const ped = useListEdit(pack.player_entities, (x) => onChange({ ...pack, player_entities: x }));
  return (
    <>
      <SectionHead title={t("rules.player_entities")} hint={t("rules.player_entities_hint")} />
      <div className="wb-panel">
        <div className="wb-grid-head wb-players">
          <span>{t("rules.pe.template")}</span>
          <span>{t("rules.g.min")}</span>
          <span>{t("rules.g.max")}</span>
          <span />
        </div>
        {pack.player_entities.map((pe, i) => (
          <div key={i} className="wb-players">
            <select value={pe.template} onChange={(e) => ped.update(i, { ...pe, template: e.target.value })}>
              {!pack.templates.some((tp) => tp.name === pe.template) && <option value={pe.template}>{t("rules.missing_template", { name: pe.template })}</option>}
              {pack.templates.map((tp) => (
                <option key={tp.name} value={tp.name}>
                  {tp.label ? `${tp.label}（${tp.name}）` : tp.name}
                </option>
              ))}
            </select>
            <input type="number" value={pe.min ?? 1} onChange={(e) => ped.update(i, { ...pe, min: Number(e.target.value) })} />
            <input type="number" value={pe.max ?? 1} onChange={(e) => ped.update(i, { ...pe, max: Number(e.target.value) })} />
            <span className="sk-side-actions">
              <Mover index={i} count={pack.player_entities.length} onMove={ped.move} />
              <button className="sk-link" onClick={() => ped.remove(i)}>
                {t("common.remove")}
              </button>
            </span>
          </div>
        ))}
        <button onClick={() => ped.add({ template: pack.templates[0]?.name ?? "", min: 1, max: 1 })}>{t("common.add")}</button>
      </div>
    </>
  );
}

export function FormulasSection({ pack, onChange, validate }: { pack: Pack; onChange: (p: Pack) => void; validate: Validate }) {
  const { t } = useI18n();
  const wb = useWorkbench();
  const fed = useListEdit(pack.formulas ?? [], (x) => onChange({ ...pack, formulas: x }));
  const vEntity = useCallback((f: string) => validate(f, null, undefined, "any_entity"), [validate]);
  return (
    <>
      <SectionHead title={t("rules.formulas")} hint={t("rules.formulas_hint")} />
      <div className="wb-panel">
        {(pack.formulas ?? []).map((f, i) => (
          <div key={i} className="wb-formula-row">
            <input value={f.name} placeholder={t("rules.ph.formula_name")} onChange={(e) => fed.update(i, { ...f, name: e.target.value })} />
            <FormulaInput value={f.formula} validate={vEntity} onChange={(x) => fed.update(i, { ...f, formula: x })} onExpand={() => wb.open(`formulas[${i}].formula`)} />
            <span className="sk-side-actions">
              <Mover index={i} count={(pack.formulas ?? []).length} onMove={fed.move} />
              <button className="sk-link" onClick={() => fed.remove(i)}>
                {t("common.remove")}
              </button>
            </span>
          </div>
        ))}
        <button onClick={() => fed.add({ name: "", formula: "", label: "" })}>{t("common.add")}</button>
      </div>
    </>
  );
}

export function TablesSection({ pack, onChange }: { pack: Pack; onChange: (p: Pack) => void }) {
  const { t } = useI18n();
  const tbl = useListEdit(pack.tables ?? [], (x) => onChange({ ...pack, tables: x }));
  return (
    <>
      <SectionHead title={t("rules.tables")} hint={t("rules.tables_hint")} />
      {(pack.tables ?? []).map((tb, i) => (
        <div key={i} className="wb-panel">
          <div className="sk-row">
            <input value={tb.name} onChange={(e) => tbl.update(i, { ...tb, name: e.target.value })} />
            <select value={tb.kind ?? "range"} onChange={(e) => tbl.update(i, { ...tb, kind: e.target.value as "range" | "exact" })}>
              <option value="range">{t("rules.table.range")}</option>
              <option value="exact">{t("rules.table.exact")}</option>
            </select>
            <Mover index={i} count={(pack.tables ?? []).length} onMove={tbl.move} />
            <button className="sk-link" onClick={() => tbl.remove(i)}>
              {t("common.remove")}
            </button>
          </div>
          <textarea
            className="sk-code"
            rows={5}
            value={tb.rows.map(([k, v]) => `${k},${v}`).join("\n")}
            onChange={(e) =>
              tbl.update(i, {
                ...tb,
                rows: e.target.value
                  .split("\n")
                  .filter((l) => l.includes(","))
                  .map((l) => {
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
    </>
  );
}

export function ChecksSection({ pack, onChange, validate }: { pack: Pack; onChange: (p: Pack) => void; validate: Validate }) {
  const { t } = useI18n();
  const wb = useWorkbench();
  const ced = useListEdit(pack.checks ?? [], (x) => onChange({ ...pack, checks: x }));
  const vNone = useCallback((f: string) => validate(f, null), [validate]);
  const vEntity = useCallback((f: string) => validate(f, null, undefined, "any_entity"), [validate]);
  const vDice = useCallback((f: string) => validate(f, null, undefined, "dice"), [validate]);
  return (
    <>
      <SectionHead title={t("rules.checks")} hint={t("rules.levels_hint")} />
      {(pack.checks ?? []).map((c, i) => (
        <div key={i} className="wb-panel">
          <div className="wb-form wb-form-check">
            <label>
              {t("rules.c.name")}
              <input value={c.name} onChange={(e) => ced.update(i, { ...c, name: e.target.value })} />
            </label>
            <label>
              {t("rules.c.dice")}
              <FormulaInput value={c.dice} validate={vDice} placeholder={t("rules.ph.dice")} onChange={(x) => ced.update(i, { ...c, dice: x })} onExpand={() => wb.open(`checks[${i}].dice`)} />
            </label>
            <label>
              {t("rules.c.target")}
              <FormulaInput value={c.target ?? "0"} validate={vEntity} onChange={(x) => ced.update(i, { ...c, target: x })} onExpand={() => wb.open(`checks[${i}].target`)} />
            </label>
            <span className="sk-side-actions">
              <Mover index={i} count={(pack.checks ?? []).length} onMove={ced.move} />
              <button className="sk-link" onClick={() => ced.remove(i)}>
                {t("common.remove")}
              </button>
            </span>
          </div>
          <h4 className="wb-sub">{t("rules.path.levels")}</h4>
          {c.levels.map((lv, j) => (
            <div key={j} className="wb-formula-row">
              <input value={lv.name} onChange={(e) => ced.update(i, { ...c, levels: c.levels.map((x, k) => (k === j ? { ...x, name: e.target.value } : x)) })} />
              <FormulaInput value={lv.condition} validate={vNone} onChange={(x) => ced.update(i, { ...c, levels: c.levels.map((y, k) => (k === j ? { ...y, condition: x } : y)) })} onExpand={() => wb.open(`checks[${i}].levels[${j}].condition`)} />
              <span className="sk-side-actions">
                <Mover index={j} count={c.levels.length} onMove={(from, to) => ced.update(i, { ...c, levels: moved(c.levels, from, to) })} />
                <button className="sk-link" onClick={() => ced.update(i, { ...c, levels: c.levels.filter((_, k) => k !== j) })}>
                  {t("common.remove")}
                </button>
              </span>
            </div>
          ))}
          <button onClick={() => ced.update(i, { ...c, levels: [...c.levels, { name: "", condition: "" }] })}>{t("rules.add_level")}</button>
        </div>
      ))}
      <button onClick={() => ced.add({ name: "", label: "", dice: "1d100", target: "0", levels: [] })}>{t("common.add")}</button>
    </>
  );
}

export function TextSection({ pack, onChange }: { pack: Pack; onChange: (p: Pack) => void }) {
  const { t } = useI18n();
  return (
    <>
      <SectionHead title={t("rules.rules_text")} hint={t("rules.rules_text_hint")} />
      <textarea className="wb-longtext" value={pack.rules_text ?? ""} onChange={(e) => onChange({ ...pack, rules_text: e.target.value })} />
    </>
  );
}

export function SamplesSection({ pack, onChange }: { pack: Pack; onChange: (p: Pack) => void }) {
  const { t } = useI18n();
  const sed = useListEdit(pack.samples ?? [], (x) => onChange({ ...pack, samples: x }));
  return (
    <>
      <SectionHead title={t("rules.samples")} hint={t("rules.samples_hint")} />
      {(pack.samples ?? []).map((s, i) => (
        <SampleEditor key={i} sample={s} templates={pack.templates.map((x) => x.name)} onChange={(x) => sed.update(i, x)} onRemove={() => sed.remove(i)} mover={<Mover index={i} count={(pack.samples ?? []).length} onMove={sed.move} />} />
      ))}
      <button onClick={() => sed.add({ name: "", template: pack.templates[0]?.name ?? "", sheet: { name: "sample", fields: {} }, expected: {} })}>{t("common.add")}</button>
      <DeriveTry pack={pack} />
    </>
  );
}

function SampleEditor({ sample, templates, onChange, onRemove, mover }: { sample: Schemas["SampleSheet"]; templates: string[]; onChange: (s: Schemas["SampleSheet"]) => void; onRemove: () => void; mover: ReactNode }) {
  const { t } = useI18n();
  const [sheetText, setSheetText] = useState(() => JSON.stringify(sample.sheet, null, 1));
  const [bad, setBad] = useState(false);
  useEffect(() => {
    // 换了位置或换了规则包时，用新的内容覆盖输入框（正在输入的不合法 JSON 不覆盖）
    let same = false;
    try {
      same = JSON.stringify(JSON.parse(sheetText)) === JSON.stringify(sample.sheet);
    } catch {
      same = bad;
    }
    if (!same) {
      setSheetText(JSON.stringify(sample.sheet, null, 1));
      setBad(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sample.sheet]);
  return (
    <div className="wb-panel">
      <div className="sk-row">
        <input value={sample.name} placeholder={t("rules.ph.sample_name")} onChange={(e) => onChange({ ...sample, name: e.target.value })} />
        <select value={sample.template} onChange={(e) => onChange({ ...sample, template: e.target.value })}>
          {templates.map((x) => (
            <option key={x} value={x}>
              {x}
            </option>
          ))}
        </select>
        {mover}
        <button className="sk-link" onClick={onRemove}>
          {t("common.remove")}
        </button>
      </div>
      <div className="wb-form">
        <label>
          {t("rules.sample_sheet")}
          <textarea
            rows={8}
            className={bad ? "sk-code invalid" : "sk-code"}
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
            rows={8}
            className="sk-code"
            value={Object.entries(sample.expected).map(([k, v]) => `${k}=${v}`).join("\n")}
            onChange={(e) =>
              onChange({
                ...sample,
                expected: Object.fromEntries(
                  e.target.value
                    .split("\n")
                    .filter((l) => l.includes("="))
                    .map((l) => {
                      const [k = "", v = "0"] = l.split("=");
                      return [k.trim(), Number(v)];
                    }),
                ),
              })
            }
          />
        </label>
      </div>
    </div>
  );
}

/** 试算：拿一张卡算推导值。 */
function DeriveTry({ pack }: { pack: Pack }) {
  const { t } = useI18n();
  const [template, setTemplate] = useState(pack.templates[0]?.name ?? "");
  const [sheet, setSheet] = useState(() => JSON.stringify(pack.samples?.[0]?.sheet ?? { name: "x", fields: {} }, null, 1));
  const act = useAction();
  const [out, setOut] = useState<Schemas["TryOut"] | null>(null);
  return (
    <>
      <h3 className="wb-sub">{t("rules.try")}</h3>
      <div className="wb-panel">
        <div className="sk-row">
          <select value={template} onChange={(e) => setTemplate(e.target.value)}>
            {pack.templates.map((x) => (
              <option key={x.name} value={x.name}>
                {x.name}
              </option>
            ))}
          </select>
          <button onClick={() => void act.run(async () => setOut(await call(api.POST("/api/admin/rulepacks/try", { body: { pack, template, sheet: JSON.parse(sheet) } }))))}>{t("rules.try_run")}</button>
        </div>
        <textarea className="sk-code" rows={6} value={sheet} onChange={(e) => setSheet(e.target.value)} />
        <ErrorBox error={act.error} />
        {out && (
          <ul className="wb-derived-out">
            {out.derived.map((d) => (
              <li key={d.name}>
                <code>{d.name}</code> = <b>{d.value}</b> <span className="sk-hint">({d.base}{d.modifiers?.length ? `; ${d.modifiers.join(", ")}` : ""})</span>
              </li>
            ))}
            {out.problems.map((p, i) => (
              <li key={i} className="sk-invalid">
                {p.code} {p.path}
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}
