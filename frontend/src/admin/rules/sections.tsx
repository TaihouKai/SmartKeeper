import { useCallback, useEffect, useState, type ReactNode } from "react";
import { api, call, type Schemas } from "../../api/client";
import { useI18n } from "../../i18n";
import { ErrorBox, FormulaInput, Mover } from "../../ui/components";
import { Markdown } from "../../ui/markdown";
import { ParamsEditor, blankParam } from "../../ui/ParamEditor";
import { useAction } from "../../ui/hooks";
import { FieldCard, blankField, useListEdit, type Validate } from "../fieldCard";
import { GroupTable } from "../GroupTable";
import { hasProblem, useWorkbench } from "./ctx";
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
export function FieldsSection({ tpl, onChange, onRemove, validate, mover, base }: { tpl: Template; onChange: (t: Template) => void; onRemove: () => void; validate: Validate; mover: ReactNode; base: string }) {
  const { t } = useI18n();
  const wb = useWorkbench();
  const vDamage = useCallback((f: string) => validate(f, tpl.name, undefined, "damage"), [validate, tpl.name]);
  const vStealth = useCallback((f: string) => validate(f, tpl.name, undefined, "stealth"), [validate, tpl.name]);
  const vSearch = useCallback((f: string) => validate(f, tpl.name, undefined, "search"), [validate, tpl.name]);
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
        <div className="wb-form wb-form-3">
          <label title={t("rules.t.name_label_hint")}>
            {t("rules.t.name_label")}
            <input value={tpl.name_label ?? ""} placeholder={t("character.name")} onChange={(e) => onChange({ ...tpl, name_label: e.target.value })} />
          </label>
          <label title={t("rules.t.name_label_hint")}>
            {t("rules.t.name_hint")}
            <input value={tpl.name_hint ?? ""} placeholder={t("character.name_hint")} onChange={(e) => onChange({ ...tpl, name_hint: e.target.value })} />
          </label>
        </div>
        <label title={t("rules.t.description_hint")}>
          {t("rules.t.description")}
          <textarea rows={2} value={tpl.description ?? ""} placeholder={t("rules.ph.ref_hint")} onChange={(e) => onChange({ ...tpl, description: e.target.value })} />
        </label>
        <label title={t("rules.t.damage_taken_hint")}>
          {t("rules.t.damage_taken")}
          <FormulaInput value={tpl.damage_taken ?? ""} validate={vDamage} placeholder={t("rules.ph.damage_taken")} onChange={(x) => onChange({ ...tpl, damage_taken: x })} onExpand={() => wb.open(`${base}.damage_taken`)} />
        </label>
        <p className="wb-hint">{t("rules.t.damage_taken_hint")}</p>
        <label title={t("rules.t.stealth_hint")}>
          {t("rules.t.stealth")}
          <FormulaInput value={tpl.stealth ?? ""} validate={vStealth} placeholder={t("rules.ph.stealth")} onChange={(x) => onChange({ ...tpl, stealth: x })} onExpand={() => wb.open(`${base}.stealth`)} />
        </label>
        <label title={t("rules.t.stealth_hint")}>
          {t("rules.t.search")}
          <FormulaInput value={tpl.search ?? ""} validate={vSearch} placeholder={t("rules.ph.search")} onChange={(x) => onChange({ ...tpl, search: x })} onExpand={() => wb.open(`${base}.search`)} />
        </label>
        <p className="wb-hint">{t("rules.t.stealth_hint")}</p>
        <div className="sk-row">
          <span>{t("rules.t.on_death")}</span>
          <button type="button" className="wb-script-btn" onClick={() => wb.open(`${base}.on_death`)}>
            {(tpl.on_death ?? "").trim() ? t("rules.t.on_death_edit") : t("rules.t.on_death_add")}
          </button>
        </div>
        <p className="wb-hint">{t("rules.t.on_death_hint")}</p>
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
      <BudgetsPanel tpl={tpl} onChange={onChange} validate={v} base={base} />
    </>
  );
}

type Budget = Schemas["BudgetDef"];

/** 合计上限（例如属性点）：哪些字段、哪些分组的哪一列合计起来，最多多少，什么时候才限制。 */
function BudgetsPanel({ tpl, onChange, validate, base }: { tpl: Template; onChange: (t: Template) => void; validate: (f: string) => ReturnType<Validate>; base: string }) {
  const { t } = useI18n();
  const wb = useWorkbench();
  const budgets = tpl.budgets ?? [];
  const ed = useListEdit(budgets, (b) => onChange({ ...tpl, budgets: b }));
  const numeric = (f: Field) => f.kind === "number" || f.kind === "boolean";
  const fieldOpts = (tpl.fields ?? []).filter((f) => (f.cls ?? "player") === "player" && numeric(f));
  const colOpts = (tpl.groups ?? []).flatMap((g) => (g.fields ?? []).filter((c) => (c.cls ?? "player") === "player" && numeric(c)).map((c) => ({ ref: `${g.name}.${c.name}`, label: `${g.label || g.name} · ${c.label || c.name}` })));
  const toggle = (list: readonly string[], x: string, on: boolean) => (on ? [...list, x] : list.filter((y) => y !== x));
  return (
    <>
      <SectionHead crumbs={[t("rules.templates"), tpl.label || tpl.name]} title={t("rules.budgets")} hint={t("rules.budgets_hint")} />
      <div className="wb-panel">
        {budgets.map((b: Budget, i) => (
          <div key={i} className="wb-budget">
            <div className="sk-derived-row">
              <input value={b.name} placeholder={t("rules.ph.budget_name")} onChange={(e) => ed.update(i, { ...b, name: e.target.value })} />
              <input value={b.label ?? ""} placeholder={t("rules.ph.budget_label")} onChange={(e) => ed.update(i, { ...b, label: e.target.value })} />
              <FormulaInput value={b.total ?? ""} validate={validate} placeholder={t("rules.ph.budget_total")} onChange={(x) => ed.update(i, { ...b, total: x })} onExpand={() => wb.open(`${base}.budgets[${i}].total`)} />
              <FormulaInput value={b.when ?? ""} validate={validate} placeholder={t("rules.ph.budget_when")} onChange={(x) => ed.update(i, { ...b, when: x })} onExpand={() => wb.open(`${base}.budgets[${i}].when`)} />
              <span className="sk-side-actions">
                <Mover index={i} count={budgets.length} onMove={ed.move} />
                <button className="sk-link" onClick={() => ed.remove(i)}>
                  {t("common.remove")}
                </button>
              </span>
            </div>
            <input className="wb-budget-desc" value={b.description ?? ""} placeholder={t("rules.ph.budget_desc")} onChange={(e) => ed.update(i, { ...b, description: e.target.value })} />
            <fieldset className="wb-budget-pick">
              <legend>{t("rules.budget_fields")}</legend>
              {fieldOpts.map((f) => (
                <label key={f.name} className="sk-inline">
                  <input type="checkbox" checked={(b.fields ?? []).includes(f.name)} onChange={(e) => ed.update(i, { ...b, fields: toggle(b.fields ?? [], f.name, e.target.checked) })} /> {f.label || f.name}
                </label>
              ))}
            </fieldset>
            {colOpts.length > 0 && (
              <fieldset className="wb-budget-pick">
                <legend>{t("rules.budget_columns")}</legend>
                {colOpts.map((c) => (
                  <label key={c.ref} className="sk-inline">
                    <input type="checkbox" checked={(b.columns ?? []).includes(c.ref)} onChange={(e) => ed.update(i, { ...b, columns: toggle(b.columns ?? [], c.ref, e.target.checked) })} /> {c.label}
                  </label>
                ))}
              </fieldset>
            )}
          </div>
        ))}
        <button onClick={() => ed.add({ name: "", label: "", description: "", fields: [], columns: [], total: "", when: "" })}>{t("rules.add_budget")}</button>
      </div>
    </>
  );
}

/** 一个分组：上面是设置（名字、数量、开关、范围形状），下面是条目表。 */
/** 修正能作用的数值：推导值，和建角时填的数值、是/否字段。 */
export function modifiable(tpl: Template): string[] {
  const fields = (tpl.fields ?? []).filter((f) => (f.cls ?? "player") === "player" && (f.kind === "number" || f.kind === "boolean")).map((f) => f.name);
  return [...(tpl.derived ?? []).map((d) => d.name), ...fields];
}

export function GroupSection({ tpl, g, onChange, onRemove, validate, base, mover, checks = [] }: { tpl: Template; g: Group; onChange: (g: Group) => void; onRemove: () => void; validate: Validate; base: string; mover: ReactNode; checks?: string[] }) {
  const { t } = useI18n();
  const allowed = g.shapes?.allowed ?? [];
  const [settings, setSettings] = useState(false);
  const vReveal = useCallback((f: string) => validate(f, tpl.name, g.name), [validate, tpl.name, g.name]);
  const flag = (key: "effects" | "hidden" | "placements" | "timing" | "reactions" | "uses", def: boolean, label: string) => (
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
        <label title={t("rules.t.description_hint")}>
          {t("rules.g.description")}
          <textarea rows={2} value={g.description ?? ""} placeholder={t("rules.ph.ref_hint")} onChange={(e) => onChange({ ...g, description: e.target.value })} />
        </label>
        <button type="button" className="sk-link wb-toggle" aria-expanded={settings} onClick={() => setSettings(!settings)}>
          {settings ? "▾" : "▸"} {t("rules.g.settings")}
        </button>
        {settings && (
          <div className="wb-settings">
            <div className="sk-field-flags">
              {flag("effects", true, t("rules.g.effects"))}
              {flag("uses", false, t("rules.g.uses"))}
              {flag("placements", true, t("rules.g.placements"))}
              {flag("timing", true, t("rules.g.timing"))}
              {flag("reactions", true, t("rules.g.reactions"))}
              {flag("hidden", false, t("rules.g.hidden"))}
            </div>
            <label className="wb-damage-kind" title={t("rules.g.damage_kind_hint")}>
              {t("rules.g.damage_kind")}
              <input value={g.damage_kind ?? ""} placeholder={t("rules.ph.damage_kind")} onChange={(e) => onChange({ ...g, damage_kind: e.target.value.trim() })} />
            </label>
            <p className="wb-hint">{t("rules.g.damage_kind_hint")}</p>
            <label title={t("rules.g.reveal_hint")}>
              {t("rules.g.reveal")}
              <FormulaInput value={g.reveal ?? ""} validate={vReveal} placeholder={t("rules.ph.reveal")} onChange={(x) => onChange({ ...g, reveal: x })} />
            </label>
            <div className="wb-shapes">
              <span className="sk-hint">{t("rules.g.reveal_fields")}</span>
              {[...(tpl.fields ?? []).map((x) => x.name), ...(tpl.derived ?? []).map((x) => x.name)].map((n) => (
                <label key={n} className="sk-inline">
                  <input type="checkbox" checked={(g.reveal_fields ?? []).includes(n)} onChange={(e) => onChange({ ...g, reveal_fields: e.target.checked ? [...(g.reveal_fields ?? []), n] : (g.reveal_fields ?? []).filter((x) => x !== n) })} /> {fieldLabel(tpl, n)}
                </label>
              ))}
            </div>
            <p className="wb-hint">{t("rules.g.reveal_hint")}</p>
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
        derived={modifiable(tpl)}
        spendTargets={(tpl.fields ?? []).filter((f) => f.kind === "number" || f.kind === "resource").map((f) => f.name)}
        checks={checks}
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

function fieldLabel(tpl: Template, name: string): string {
  const f = (tpl.fields ?? []).find((x) => x.name === name) ?? (tpl.derived ?? []).find((x) => x.name === name);
  return f?.label ? `${f.label}（${name}）` : name;
}

/** 看见就知道：观察者感知到对象时，引擎自动告诉玩家对象卡上的哪些东西。 */
export function InsightsSection({ pack, onChange, validate }: { pack: Pack; onChange: (p: Pack) => void; validate: Validate }) {
  const { t } = useI18n();
  const rules = pack.insights ?? [];
  const ed = useListEdit(rules, (x) => onChange({ ...pack, insights: x }));
  const toggle = (list: string[], v: string, on: boolean) => (on ? [...list, v] : list.filter((x) => x !== v));
  const names = (r: (typeof rules)[number], key: "fields" | "groups"): string[] => {
    const subjects = pack.templates.filter((x) => (r.subjects ?? []).length === 0 || (r.subjects ?? []).includes(x.name));
    const of = (x: Template): string[] => (key === "groups" ? (x.groups ?? []).map((g) => g.name) : [...(x.fields ?? []).map((f) => f.name), ...(x.derived ?? []).map((d) => d.name)]);
    const first = subjects[0];
    if (first === undefined) return [];
    return of(first).filter((n) => subjects.every((x) => of(x).includes(n)));
  };
  return (
    <>
      <SectionHead title={t("rules.insights")} hint={t("rules.insights_hint")} />
      {rules.map((r, i) => {
        const observers = r.observers ?? [];
        const subjects = r.subjects ?? [];
        const tpl = observers.length === 1 ? (observers[0] ?? null) : null;
        const subjectTpl = pack.templates.find((x) => x.name === subjects[0]);
        return (
          <div key={i} className="wb-panel">
            <div className="sk-row">
              <input value={r.name} placeholder={t("rules.ph.insight_name")} onChange={(e) => ed.update(i, { ...r, name: e.target.value })} />
              <Mover index={i} count={rules.length} onMove={ed.move} />
              <button className="sk-link" onClick={() => ed.remove(i)}>
                {t("common.remove")}
              </button>
            </div>
            <label>
              {t("rules.ins.description")}
              <input value={r.description ?? ""} onChange={(e) => ed.update(i, { ...r, description: e.target.value })} />
            </label>
            {(["observers", "subjects"] as const).map((key) => (
              <div key={key} className="wb-shapes">
                <span className="sk-hint">{t(`rules.ins.${key}`)}</span>
                {pack.templates.map((x) => (
                  <label key={x.name} className="sk-inline">
                    <input type="checkbox" checked={(r[key] ?? []).includes(x.name)} onChange={(e) => ed.update(i, { ...r, [key]: toggle(r[key] ?? [], x.name, e.target.checked) })} /> {x.label || x.name}
                  </label>
                ))}
              </div>
            ))}
            <label title={t("rules.ins.when_hint")}>
              {t("rules.ins.when")}
              <FormulaInput value={r.when ?? ""} validate={(f) => validate(f, tpl, undefined, tpl ? undefined : "any_entity")} placeholder={t("rules.ph.insight_when")} onChange={(x) => ed.update(i, { ...r, when: x })} />
            </label>
            {(["fields", "groups"] as const).map((key) => (
              <div key={key} className="wb-shapes">
                <span className="sk-hint">{t(`rules.ins.${key}`)}</span>
                {names(r, key).map((n) => (
                  <label key={n} className="sk-inline">
                    <input type="checkbox" checked={(r[key] ?? []).includes(n)} onChange={(e) => ed.update(i, { ...r, [key]: toggle(r[key] ?? [], n, e.target.checked) })} /> {key === "fields" && subjectTpl ? fieldLabel(subjectTpl, n) : n}
                  </label>
                ))}
              </div>
            ))}
          </div>
        );
      })}
      {rules.length === 0 && <p className="sk-hint">{t("rules.insights_empty")}</p>}
      <button onClick={() => ed.add({ name: "", description: "", observers: [], subjects: [], when: "", fields: [], groups: [] })}>{t("common.add")}</button>
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
          <TableRows rows={tb.rows} onChange={(rows) => tbl.update(i, { ...tb, rows })} />
        </div>
      ))}
      <button onClick={() => tbl.add({ name: "", kind: "range", rows: [] })}>{t("common.add")}</button>
    </>
  );
}

type Row = Pack["tables"][number]["rows"][number];

/** 一行 “键,值”：键是数或文字，值必须是数。看不懂的行返回 null。 */
function parseRow(line: string): Row | null {
  const at = line.lastIndexOf(",") >= 0 ? line.lastIndexOf(",") : line.lastIndexOf("，");
  if (at < 0) return null;
  const k = line.slice(0, at).trim();
  const v = line.slice(at + 1).trim();
  if (!k || v === "" || Number.isNaN(Number(v))) return null;
  const num = Number(k);
  return [Number.isNaN(num) ? k : num, Number(v)];
}

/** 表的内容：一行一个“键,值”。打的字原样留着（不会被改写、光标不会跳），能看懂的行才存进规则包；看不懂的行列出来。 */
function TableRows({ rows, onChange }: { rows: Row[]; onChange: (rows: Row[]) => void }) {
  const { t } = useI18n();
  const asText = (r: Row[]) => r.map(([k, v]) => `${k},${v}`).join("\n");
  const [text, setText] = useState(() => asText(rows));
  // 外面换了（打开别的规则包、撤销）时才用规则包里的内容覆盖
  useEffect(() => {
    const mine = text.split("\n").map(parseRow).filter((x): x is Row => x !== null);
    if (JSON.stringify(mine) !== JSON.stringify(rows)) setText(asText(rows));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows]);
  const bad = text
    .split("\n")
    .map((line, i) => ({ line, i }))
    .filter(({ line }) => line.trim() && parseRow(line) === null);
  return (
    <>
      <textarea
        className={bad.length ? "sk-code invalid" : "sk-code"}
        rows={Math.max(5, text.split("\n").length + 1)}
        value={text}
        placeholder={t("rules.ph.table_rows")}
        onChange={(e) => {
          setText(e.target.value);
          onChange(e.target.value.split("\n").map(parseRow).filter((x): x is Row => x !== null));
        }}
      />
      {bad.length > 0 && (
        <small className="sk-invalid">
          {t("rules.table.bad_rows", { lines: bad.map((b) => String(b.i + 1)).join(", ") })}
        </small>
      )}
    </>
  );
}

export function blankCheck(): Pack["checks"][number] {
  return { name: "", config: "" };
}

/** 检定：每个一行，名字和“编辑”（在 IDE 里写它的代码：骰子、目标值、四种结果的条件、对抗时对方掷什么）。 */
export function ChecksSection({ pack, onChange }: { pack: Pack; onChange: (p: Pack) => void }) {
  const { t } = useI18n();
  const wb = useWorkbench();
  const ced = useListEdit(pack.checks ?? [], (x) => onChange({ ...pack, checks: x }));
  const checks = pack.checks ?? [];
  return (
    <>
      <SectionHead title={t("rules.checks")} hint={t("rules.checks_hint")} />
      <div className="wb-panel wb-check-list">
        {checks.length === 0 && <p className="sk-hint">{t("rules.checks_empty")}</p>}
        {checks.map((c, i) => {
          const path = `checks[${i}].config`;
          const label = /^\s*label\s*=\s*["'](.*)["']/m.exec(c.config ?? "")?.[1] ?? "";
          const bad = hasProblem(wb.problems, `checks[${i}]`);
          return (
            <div key={i} className={wb.active === path ? "wb-check-row active" : "wb-check-row"}>
              <input value={c.name} placeholder={t("rules.ph.check_name")} onChange={(e) => ced.update(i, { ...c, name: e.target.value })} />
              <span className="wb-check-label">{label}</span>
              <button type="button" className={`wb-script-btn ${bad ? "bad" : c.config?.trim() ? "ok" : "empty"}`} onClick={() => wb.open(path)}>
                <span className="wb-dot" />
                {t("rules.gt.edit")}
              </button>
              <span className="sk-side-actions">
                <Mover index={i} count={checks.length} onMove={ced.move} />
                <button className="sk-link" onClick={() => ced.remove(i)}>
                  {t("common.remove")}
                </button>
              </span>
            </div>
          );
        })}
        <button onClick={() => ced.add(blankCheck())}>{t("common.add")}</button>
      </div>
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

/** 默认参数：使用时选的数（例如“用＋”“投入多少魔力”），各自适用于哪些分组。 */
export function PackParamsSection({ pack, onChange, validate }: { pack: Pack; onChange: (p: Pack) => void; validate: Validate }) {
  const { t } = useI18n();
  const params = pack.params ?? [];
  const groups = [...new Set(pack.templates.flatMap((x) => (x.groups ?? []).map((g) => g.name)))];
  const checks = (pack.checks ?? []).map((c) => c.name);
  const spendTargets = [...new Set(pack.templates.flatMap((x) => (x.fields ?? []).filter((f) => f.kind === "number" || f.kind === "resource").map((f) => f.name)))];
  const set = (i: number, p: (typeof params)[number]) => onChange({ ...pack, params: params.map((x, j) => (j === i ? p : x)) });
  return (
    <>
      <SectionHead title={t("rules.params")} hint={t("rules.params_hint")} />
      {params.map((prm, i) => {
        const first = pack.templates.find((x) => (x.groups ?? []).some((g) => (prm.groups ?? []).includes(g.name)));
        const inGroup = (prm.groups ?? [])[0];
        return (
          <div key={i} className="wb-panel">
            <div className="wb-shapes">
              <span className="sk-hint">{t("rules.params_groups")}</span>
              {groups.map((g) => (
                <label key={g} className="sk-inline">
                  <input type="checkbox" checked={(prm.groups ?? []).includes(g)} onChange={(e) => set(i, { ...prm, groups: e.target.checked ? [...(prm.groups ?? []), g] : (prm.groups ?? []).filter((x) => x !== g) })} /> {g}
                </label>
              ))}
            </div>
            <ParamsEditor
              params={[prm]}
              onChange={(ps) => (ps.length ? set(i, { ...ps[0]!, groups: prm.groups ?? [] }) : onChange({ ...pack, params: params.filter((_, j) => j !== i) }))}
              validate={(f) => validate(f, first?.name ?? null, inGroup)}
              validateScript={(f) => validate(f, first?.name ?? null, inGroup, "script")}
              checks={checks}
              spendTargets={spendTargets}
              title={prm.label || prm.name || t("rules.params_untitled")}
            />
          </div>
        );
      })}
      <button onClick={() => onChange({ ...pack, params: [...params, { ...blankParam(), groups: [] }] })}>{t("common.add")}</button>
    </>
  );
}

/** 规则书：给玩家看的完整规则（Markdown）。说明里写 [[标题]] 就在建卡页上展开这一节。 */
export function HandbookSection({ pack, onChange }: { pack: Pack; onChange: (p: Pack) => void }) {
  const { t } = useI18n();
  const [preview, setPreview] = useState(false);
  return (
    <>
      <SectionHead
        title={t("rules.handbook")}
        hint={t("rules.handbook_hint")}
        actions={
          <button className="sk-link" onClick={() => setPreview(!preview)}>
            {t(preview ? "rules.handbook_edit" : "rules.handbook_preview")}
          </button>
        }
      />
      {preview ? <Markdown text={pack.handbook ?? ""} /> : <textarea className="wb-longtext" value={pack.handbook ?? ""} onChange={(e) => onChange({ ...pack, handbook: e.target.value })} />}
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
