import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { api, call, type Schemas } from "../api/client";
import { useI18n } from "../i18n";
import { ErrorBox, Fold, FormulaInput, Mover, Section, moved } from "../ui/components";
import { FieldCard, blankField, useListEdit, type Validate } from "./fieldCard";
import { GroupTable } from "./GroupTable";
import { translateCode } from "../ui/errors";
import { FormulaHelp } from "../ui/FormulaHelp";
import { useAction, usePoll } from "../ui/hooks";

type Pack = Schemas["RulePack"];
type Template = Schemas["EntityTemplate"];
type Field = Schemas["FieldDef"];
type Group = Schemas["GroupDef"];

const SHAPES = ["capsule", "box", "sphere", "cone"] as const;

export const REQUIRED_DERIVED = ["perception_radius", "concealment", "move_speed", "fly_multiplier", "fly_speed", "hear_multiplier", "hear_distance"];
const FLY_FIELD = "can_fly";

const DEFAULT_FORMULA: Record<string, string> = { concealment: "1", fly_multiplier: "1", fly_speed: "fly_multiplier * move_speed", hear_multiplier: "1" };
const DEFAULT_UNIT: Record<string, string> = { perception_radius: "m", move_speed: "m/min", fly_speed: "m/min", hear_distance: "m" };

type T = (k: string) => string;

export function blankPack(t: T): Pack {
  return {
    world: { name: "", description: "", canon: "", reference_sites: [] },
    templates: [blankTemplate("character", t)],
    player_entities: [{ template: "character", min: 1, max: 1 }],
    formulas: [],
    tables: [],
    checks: [],
    rules_text: "",
    samples: [],
  };
}

/** 引擎必需项的默认显示名（按界面语言），也是它们显示名框里的提示。 */
const REQUIRED_FIELDS = ["appearance", FLY_FIELD];
function defaultLabel(t: T, name: string): string {
  return t(`rules.default_label.${name}`);
}

/** 以前存的规则包可能缺少后来新增的引擎必需项（能否飞行字段、飞行速度等推导值）：打开时补上默认的；必需项的显示名空着就填默认的。 */
function withEngineDefaults(p: Pack, t: T): Pack {
  const blank = blankTemplate("x", t);
  const named = <X extends { name: string; label?: string }>(x: X): X => (x.label ? x : { ...x, label: defaultLabel(t, x.name) });
  return {
    ...p,
    templates: p.templates.map((tpl) => {
      const fields = tpl.fields ?? [];
      const derived = tpl.derived ?? [];
      const fly = blank.fields?.find((f) => f.name === FLY_FIELD);
      const allFields = fly && !fields.some((f) => f.name === FLY_FIELD) ? [...fields, fly] : fields;
      const allDerived = [...derived, ...(blank.derived ?? []).filter((d) => !derived.some((x) => x.name === d.name))];
      return {
        ...tpl,
        fields: allFields.map((f) => (REQUIRED_FIELDS.includes(f.name) ? named(f) : f)),
        derived: allDerived.map((d) => (REQUIRED_DERIVED.includes(d.name) ? named(d) : d)),
      };
    }),
  };
}

/** 改了模板 ID：建角实体和例题里引用它的地方跟着改。 */
function renameTemplate(pack: Pack, i: number, next: Template): Pack {
  const prev = pack.templates[i]?.name;
  const templates = pack.templates.map((x, j) => (j === i ? next : x));
  if (!prev || prev === next.name) return { ...pack, templates };
  return {
    ...pack,
    templates,
    player_entities: pack.player_entities.map((pe) => (pe.template === prev ? { ...pe, template: next.name } : pe)),
    samples: (pack.samples ?? []).map((sm) => (sm.template === prev ? { ...sm, template: next.name } : sm)),
  };
}

function blankTemplate(name: string, t: T): Template {
  return {
    name,
    label: "",
    appearance_field: "appearance",
    fields: [
      { name: "appearance", label: defaultLabel(t, "appearance"), description: "", kind: "text", cls: "player", required: true, hidden: false, choices: [] },
      { name: FLY_FIELD, label: defaultLabel(t, FLY_FIELD), description: "", kind: "boolean", cls: "player", required: true, hidden: false, choices: [] },
    ],
    groups: [],
    derived: REQUIRED_DERIVED.map((n) => ({
      name: n,
      label: defaultLabel(t, n),
      formula: DEFAULT_FORMULA[n] ?? "",
      unit: DEFAULT_UNIT[n] ?? null,
      hidden: false,
    })),
  };
}

function FieldsTable({
  fields,
  onChange,
  validate,
  template,
  appearance,
  inGroup = false,
}: {
  fields: Field[];
  onChange: (f: Field[]) => void;
  validate: Validate;
  template: string;
  appearance?: string;
  inGroup?: boolean;
}) {
  const { t } = useI18n();
  const ed = useListEdit(fields, onChange);
  const v = useCallback((f: string) => validate(f, template), [validate, template]);
  return (
    <div>
      {fields.map((f, i) => (
        <FieldCard
          key={i}
          f={f}
          validate={v}
          inGroup={inGroup}
          isAppearance={!inGroup && !!appearance && f.name === appearance}
          isFly={!inGroup && f.name === FLY_FIELD}
          onChange={(x) => ed.update(i, x)}
          onRemove={() => ed.remove(i)}
          mover={<Mover index={i} count={fields.length} onMove={ed.move} />}
        />
      ))}
      <button onClick={() => ed.add(blankField())}>{t("rules.add_field")}</button>
    </div>
  );
}

function GroupCard({ g, onChange, onRemove, validate, template, derived, mover, spendTargets }: { g: Group; onChange: (g: Group) => void; onRemove: () => void; validate: Validate; template: string; derived: string[]; mover: ReactNode; spendTargets: string[] }) {
  const { t } = useI18n();
  const allowed = g.shapes?.allowed ?? [];
  return (
    <div className="sk-card">
      <Fold level={5} title={g.label || g.name || t("rules.g.untitled")}>
        <div className="sk-group-main">
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
          <div className="sk-field-side sk-side-actions">
            {mover}
            <button className="sk-link" onClick={onRemove}>
              {t("common.remove")}
            </button>
          </div>
        </div>
        <div className="sk-field-flags">
          <label className="sk-inline">
            <input type="checkbox" checked={g.effects ?? true} onChange={(e) => onChange({ ...g, effects: e.target.checked })} /> {t("rules.g.effects")}
          </label>
          <label className="sk-inline">
            <input type="checkbox" checked={g.hidden ?? false} onChange={(e) => onChange({ ...g, hidden: e.target.checked })} /> {t("rules.g.hidden")}
          </label>
        </div>
        <label>{t("rules.g.shapes")}</label>
        <div className="sk-shapes">
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
        <Fold level={5} title={t("rules.gt.title")} hint={t("rules.gt.hint")}>
          <GroupTable g={g} onChange={onChange} validate={validate} template={template} derived={derived} spendTargets={spendTargets} />
        </Fold>
      </Fold>
    </div>
  );
}

function TemplateEditor({ tpl, onChange, onRemove, validate, mover }: { tpl: Template; onChange: (t: Template) => void; onRemove: () => void; validate: Validate; mover: ReactNode }) {
  const { t } = useI18n();
  const groups = tpl.groups ?? [];
  const derived = tpl.derived ?? [];
  const ged = useListEdit(groups, (g) => onChange({ ...tpl, groups: g }));
  const ded = useListEdit(derived, (d) => onChange({ ...tpl, derived: d }));
  const v = useCallback((f: string) => validate(f, tpl.name), [validate, tpl.name]);
  return (
    <div className="sk-card">
      <Fold level={4} title={tpl.label || tpl.name}>
        <p className="sk-hint">{t("rules.template_hint")}</p>
        <div className="sk-row">
          <label>{t("rules.t.name")}<input value={tpl.name} placeholder={t("rules.ph.template_name")} onChange={(e) => onChange({ ...tpl, name: e.target.value })} /></label>
          <label>{t("rules.t.label")}<input value={tpl.label ?? ""} placeholder={t("rules.ph.template_label")} onChange={(e) => onChange({ ...tpl, label: e.target.value })} /></label>
          {mover}
          <button className="sk-link" onClick={onRemove}>{t("rules.remove_template")}</button>
        </div>
        <Fold level={5} title={t("rules.fields")} hint={t("rules.fields_hint")}>
          <FieldsTable fields={tpl.fields ?? []} onChange={(f) => onChange({ ...tpl, fields: f })} validate={validate} template={tpl.name} appearance={tpl.appearance_field ?? "appearance"} />
        </Fold>
        <Fold level={5} title={t("rules.derived")} hint={t("rules.derived_hint")}>
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
                  <input value={d.name} disabled={required} title={required ? t("rules.locked") : undefined} placeholder={t("rules.ph.derived_name")} onChange={(e) => ded.update(i, { ...d, name: e.target.value })} />
                  <input value={d.label ?? ""} placeholder={required ? t(`rules.ph.label_${d.name}`) : t("rules.ph.derived_label")} onChange={(e) => ded.update(i, { ...d, label: e.target.value })} />
                  <FormulaInput value={d.formula} validate={v} placeholder={required ? t(`rules.ph.formula_${d.name}`) : t("rules.ph.formula")} onChange={(x) => ded.update(i, { ...d, formula: x })} />
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
        </Fold>
        <Fold level={5} title={t("rules.groups")} hint={t("rules.groups_hint")}>
          {groups.map((g: Group, i) => (
            <GroupCard key={i} g={g} template={tpl.name} derived={derived.map((d) => d.name)} spendTargets={(tpl.fields ?? []).filter((f) => f.kind === "number" || f.kind === "resource").map((f) => f.name)} validate={validate} onChange={(x) => ged.update(i, x)} onRemove={() => ged.remove(i)} mover={<Mover index={i} count={groups.length} onMove={ged.move} />} />
          ))}
          <button onClick={() => ged.add({ name: "", label: "", fields: [], presets: [], min_count: 0, max_count: null, effects: true, shapes: { allowed: [] }, hidden: false })}>{t("rules.add_group")}</button>
        </Fold>
      </Fold>
    </div>
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
  const vEntity = useCallback((f: string) => validate(f, null, undefined, "any_entity"), [validate]);
  const vDice = useCallback((f: string) => validate(f, null, undefined, "dice"), [validate]);
  const w = pack.world;
  return (
    <div>
      <Fold title={t("rules.world")}>
      <label>{t("rules.w.name")}<input value={w.name} onChange={(e) => onChange({ ...pack, world: { ...w, name: e.target.value } })} /></label>
      <label>{t("rules.w.canon")}<input value={w.canon ?? ""} onChange={(e) => onChange({ ...pack, world: { ...w, canon: e.target.value } })} /></label>
      <label>{t("rules.w.description")}<textarea rows={3} value={w.description ?? ""} onChange={(e) => onChange({ ...pack, world: { ...w, description: e.target.value } })} /></label>
      <label>{t("rules.w.sites")}<textarea rows={2} value={(w.reference_sites ?? []).join("\n")} onChange={(e) => onChange({ ...pack, world: { ...w, reference_sites: e.target.value.split("\n").map((x) => x.trim()).filter(Boolean) } })} /></label>
      </Fold>

      <Fold title={t("rules.templates")}>
      {pack.templates.map((tp, i) => (
        <TemplateEditor key={i} tpl={tp} validate={validate} onChange={(x) => onChange(renameTemplate(pack, i, x))} onRemove={() => ted.remove(i)} mover={<Mover index={i} count={pack.templates.length} onMove={ted.move} />} />
      ))}
      <button onClick={() => ted.add(blankTemplate(`template_${pack.templates.length + 1}`, t))}>{t("rules.add_template")}</button>
      </Fold>

      <Fold title={t("rules.player_entities")}>
      {pack.player_entities.map((pe, i) => (
        <div key={i} className="sk-row">
          <select value={pe.template} onChange={(e) => ped.update(i, { ...pe, template: e.target.value })}>
            {!pack.templates.some((tp) => tp.name === pe.template) && <option value={pe.template}>{t("rules.missing_template", { name: pe.template })}</option>}
            {pack.templates.map((tp) => <option key={tp.name} value={tp.name}>{tp.label ? `${tp.label}（${tp.name}）` : tp.name}</option>)}
          </select>
          <input type="number" value={pe.min ?? 1} onChange={(e) => ped.update(i, { ...pe, min: Number(e.target.value) })} />
          <input type="number" value={pe.max ?? 1} onChange={(e) => ped.update(i, { ...pe, max: Number(e.target.value) })} />
          <Mover index={i} count={pack.player_entities.length} onMove={ped.move} />
          <button className="sk-link" onClick={() => ped.remove(i)}>{t("common.remove")}</button>
        </div>
      ))}
      <button onClick={() => ped.add({ template: pack.templates[0]?.name ?? "", min: 1, max: 1 })}>{t("common.add")}</button>
      </Fold>

      <Fold title={t("rules.formulas")}>
      {(pack.formulas ?? []).map((f, i) => (
        <div key={i} className="sk-row">
          <input value={f.name} onChange={(e) => fed.update(i, { ...f, name: e.target.value })} />
          <FormulaInput value={f.formula} validate={vEntity} onChange={(x) => fed.update(i, { ...f, formula: x })} />
          <Mover index={i} count={(pack.formulas ?? []).length} onMove={fed.move} />
          <button className="sk-link" onClick={() => fed.remove(i)}>{t("common.remove")}</button>
        </div>
      ))}
      <button onClick={() => fed.add({ name: "", formula: "", label: "" })}>{t("common.add")}</button>
      </Fold>

      <Fold title={t("rules.tables")} hint={t("rules.tables_hint")}>
      {(pack.tables ?? []).map((tb, i) => (
        <div key={i} className="sk-card">
          <div className="sk-row">
            <input value={tb.name} onChange={(e) => tbl.update(i, { ...tb, name: e.target.value })} />
            <select value={tb.kind ?? "range"} onChange={(e) => tbl.update(i, { ...tb, kind: e.target.value as "range" | "exact" })}>
              <option value="range">{t("rules.table.range")}</option>
              <option value="exact">{t("rules.table.exact")}</option>
            </select>
            <Mover index={i} count={(pack.tables ?? []).length} onMove={tbl.move} />
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
      </Fold>

      <Fold title={t("rules.checks")}>
      {(pack.checks ?? []).map((c, i) => (
        <div key={i} className="sk-card">
          <div className="sk-row">
            <label>{t("rules.c.name")}<input value={c.name} onChange={(e) => ced.update(i, { ...c, name: e.target.value })} /></label>
            <label>{t("rules.c.dice")}<FormulaInput value={c.dice} validate={vDice} placeholder={t("rules.ph.dice")} onChange={(x) => ced.update(i, { ...c, dice: x })} /></label>
            <label>{t("rules.c.target")}<FormulaInput value={c.target ?? "0"} validate={vEntity} onChange={(x) => ced.update(i, { ...c, target: x })} /></label>
            <Mover index={i} count={(pack.checks ?? []).length} onMove={ced.move} />
            <button className="sk-link" onClick={() => ced.remove(i)}>{t("common.remove")}</button>
          </div>
          {c.levels.map((lv, j) => (
            <div key={j} className="sk-row">
              <input value={lv.name} onChange={(e) => ced.update(i, { ...c, levels: c.levels.map((x, k) => (k === j ? { ...x, name: e.target.value } : x)) })} />
              <FormulaInput value={lv.condition} validate={vNone} onChange={(x) => ced.update(i, { ...c, levels: c.levels.map((y, k) => (k === j ? { ...y, condition: x } : y)) })} />
              <Mover index={j} count={c.levels.length} onMove={(from, to) => ced.update(i, { ...c, levels: moved(c.levels, from, to) })} />
              <button className="sk-link" onClick={() => ced.update(i, { ...c, levels: c.levels.filter((_, k) => k !== j) })}>{t("common.remove")}</button>
            </div>
          ))}
          <button onClick={() => ced.update(i, { ...c, levels: [...c.levels, { name: "", condition: "" }] })}>{t("rules.add_level")}</button>
          <p className="sk-hint">{t("rules.levels_hint")}</p>
        </div>
      ))}
      <button onClick={() => ced.add({ name: "", label: "", dice: "1d100", target: "0", levels: [] })}>{t("common.add")}</button>
      </Fold>

      <Fold title={t("rules.rules_text")}>
      <textarea rows={8} value={pack.rules_text ?? ""} onChange={(e) => onChange({ ...pack, rules_text: e.target.value })} />
      </Fold>

      <Fold title={t("rules.samples")} hint={t("rules.samples_hint")}>
      {(pack.samples ?? []).map((s, i) => (
        <SampleEditor key={i} sample={s} templates={pack.templates.map((x) => x.name)} onChange={(x) => sed.update(i, x)} onRemove={() => sed.remove(i)} mover={<Mover index={i} count={(pack.samples ?? []).length} onMove={sed.move} />} />
      ))}
      <button onClick={() => sed.add({ name: "", template: pack.templates[0]?.name ?? "", sheet: { name: "sample", fields: {} }, expected: {} })}>{t("common.add")}</button>
      </Fold>
    </div>
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
    <div className="sk-card">
      <div className="sk-row">
        <input value={sample.name} onChange={(e) => onChange({ ...sample, name: e.target.value })} />
        <select value={sample.template} onChange={(e) => onChange({ ...sample, template: e.target.value })}>
          {templates.map((x) => <option key={x} value={x}>{x}</option>)}
        </select>
        {mover}
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
      <Fold title={t("rules.try")}>
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
      </Fold>
    </div>
  );
}

/** 把问题路径（templates[0].fields[2]）换成看得懂的名字（模板 hero › 字段 hp）。 */
function describePath(t: (k: string) => string, pack: Pack, path: string): string {
  if (!path || path === ".") return "";
  let obj: unknown = pack;
  const out: string[] = [];
  for (const seg of path.split(".")) {
    const m = /^(\w+)\[(\d+)\]$/.exec(seg);
    const key = m?.[1] ?? seg;
    const label = t(`rules.path.${key}`);
    const known = label !== `rules.path.${key}`;
    obj = obj && typeof obj === "object" ? (obj as Record<string, unknown>)[key] : undefined;
    if (m) {
      const idx = Number(m[2]);
      obj = Array.isArray(obj) ? obj[idx] : undefined;
      const rec = obj && typeof obj === "object" ? (obj as Record<string, unknown>) : {};
      const name = typeof rec.label === "string" && rec.label ? rec.label : typeof rec.name === "string" && rec.name ? rec.name : `#${idx + 1}`;
      out.push(known ? `${label} ${name}` : `${key} ${name}`);
    } else {
      out.push(known ? label : seg);
    }
  }
  return out.join(" › ");
}

function when(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleString() : "";
}

/** “规则”面板：新建和编辑规则包、草稿、试算、版本管理、导入导出。 */
export function RulesPanel() {
  const { t, lang } = useI18n();
  const packs = usePoll(() => call(api.GET("/api/admin/rulepacks")), 600_000);
  const [current, setCurrent] = useState<{ id: string | null; version: number | null }>({ id: null, version: null });
  const [pack, setPack] = useState<Pack>(() => blankPack(t));
  const [problems, setProblems] = useState<Schemas["Problem"][] | null>(null);
  const [checkError, setCheckError] = useState<unknown>(null);
  const [draftAt, setDraftAt] = useState<string | null>(null);
  const [draftError, setDraftError] = useState<unknown>(null);
  const [help, setHelp] = useState(false);
  const [choice, setChoice] = useState("");
  const act = useAction();
  // 上次打开或保存时的内容；和它不同就是“有未保存的修改”
  const baseline = useRef(JSON.stringify(pack));
  const idRef = useRef<string | null>(null);
  const creating = useRef<Promise<string> | null>(null);
  idRef.current = current.id;
  const dirty = JSON.stringify(pack) !== baseline.current;

  const load = (p: Pack, id: string | null, version: number | null, draft: string | null) => {
    // 基准是原样的内容：补了引擎新增的必需项就算有修改，几秒后自动存成草稿
    baseline.current = JSON.stringify(p);
    setPack(withEngineDefaults(p, t));
    setCurrent({ id, version });
    setDraftAt(draft);
    setChoice(id ? `${id}|${version ?? "draft"}` : "");
  };

  const validate: Validate = useCallback(
    (formula, template, inEntry, scope) =>
      call(api.POST("/api/admin/rulepacks/formula", { body: { pack, formula, template, in_entry: inEntry ?? null, scope: scope ?? null } })),
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

  /** 当前规则包的 id；新规则包第一次保存时才创建（并发的自动保存只创建一次）。 */
  const ensureId = async (): Promise<string> => {
    if (idRef.current) return idRef.current;
    creating.current ??= call(api.POST("/api/admin/rulepacks", { body: { name: pack.world.name || "rulepack" } })).then((r) => r.pack_id);
    const id = await creating.current;
    creating.current = null;
    idRef.current = id;
    return id;
  };

  const saveDraft = async (p: Pack) => {
    const id = await ensureId();
    const d = await call(api.PUT("/api/admin/rulepacks/{pack_id}/draft", { params: { path: { pack_id: id } }, body: { pack: p } }));
    baseline.current = JSON.stringify(p);
    setCurrent((c) => ({ id, version: c.id === id ? c.version : null }));
    setDraftAt(d.updated_at);
    setDraftError(null);
    setChoice(`${id}|draft`);
    void packs.refresh();
  };

  // 有修改就在停手 3 秒后自动存草稿
  useEffect(() => {
    if (!dirty) return;
    const id = window.setTimeout(() => {
      saveDraft(pack).catch((e: unknown) => setDraftError(e));
    }, 3000);
    return () => window.clearTimeout(id);
  }, [pack, dirty]);

  const open = (id: string, version: number) =>
    void act.run(async () => {
      const v = await call(api.GET("/api/admin/rulepacks/{pack_id}/versions/{version}", { params: { path: { pack_id: id, version } } }));
      load(v.pack, id, version, null);
    });
  const openDraft = (id: string) =>
    void act.run(async () => {
      const d = await call(api.GET("/api/admin/rulepacks/{pack_id}/draft", { params: { path: { pack_id: id } } }));
      load(d.pack, id, null, d.updated_at);
    });
  const discardDraft = (id: string) =>
    void act.run(async () => {
      await call(api.DELETE("/api/admin/rulepacks/{pack_id}/draft", { params: { path: { pack_id: id } } }));
      if (current.id === id) load(blankPack(t), null, null, null);
      setChoice("");
      void packs.refresh();
    });
  const save = () =>
    void act.run(async () => {
      const id = await ensureId();
      const v = await call(api.POST("/api/admin/rulepacks/{pack_id}/versions", { params: { path: { pack_id: id } }, body: { pack } }));
      load(pack, id, v.version, null);
      void packs.refresh();
    });
  const importFile = (file: File) =>
    void act.run(async () => {
      const v = await call(api.POST("/api/admin/rulepacks/import", { body: { text: await file.text() } }));
      load(v.pack, v.pack_id, v.version, null);
      void packs.refresh();
    });
  const remove = (id: string, version: number) =>
    void act.run(async () => {
      await call(api.DELETE("/api/admin/rulepacks/{pack_id}/versions/{version}", { params: { path: { pack_id: id, version } } }));
      setChoice("");
      void packs.refresh();
    });

  // 下拉菜单里选中的一项：规则包 id 加版本号（草稿是 null）
  const [pid = "", ver = ""] = choice.split("|");
  const picked = choice ? { id: pid, version: ver === "draft" ? null : Number(ver) } : null;

  let editing = t("rules.editing_new");
  if (current.id && current.version !== null) editing = t("rules.editing", { id: current.id, version: String(current.version) });
  else if (current.id) editing = t("rules.editing_draft", { id: current.id });

  return (
    <div className={help ? "sk-with-drawer" : undefined}>
      <Section title={t("admin.panel.rules")}>
      <div className="sk-card">
        <h3>{t("rules.packs")}</h3>
        <div className="sk-row sk-pack-picker">
          <select value={choice} onChange={(e) => setChoice(e.target.value)}>
            <option value="">{t("rules.pick")}</option>
            {(packs.data ?? []).map((p) => (
              <optgroup key={p.pack_id} label={p.name || p.pack_id}>
                {p.draft_updated_at && <option value={`${p.pack_id}|draft`}>{t("rules.draft_chip", { time: when(p.draft_updated_at) })}</option>}
                {[...p.versions].reverse().map((v) => (
                  <option key={v} value={`${p.pack_id}|${v}`}>
                    {t("rules.version", { v: String(v) })}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
          <button className="sk-primary" disabled={!picked} onClick={() => picked && (picked.version === null ? openDraft(picked.id) : open(picked.id, picked.version))}>
            {t("rules.open")}
          </button>
          {picked && picked.version !== null && (
            <a className="sk-button" href={`/api/admin/rulepacks/${picked.id}/versions/${picked.version}/export`}>
              {t("rules.export")}
            </a>
          )}
          {picked && (
            <button onClick={() => (picked.version === null ? discardDraft(picked.id) : remove(picked.id, picked.version))}>
              {picked.version === null ? t("rules.draft_discard") : t("common.remove")}
            </button>
          )}
        </div>
        <div className="sk-row">
          <button onClick={() => load(blankPack(t), null, null, null)}>{t("rules.new")}</button>
          <label className="sk-button sk-file">
            {t("rules.import")}
            <input type="file" accept=".json,application/json" onChange={(e) => e.target.files?.[0] && importFile(e.target.files[0])} />
          </label>
        </div>
      </div>
      <p className="sk-hint">{editing}</p>
      <PackEditor pack={pack} onChange={setPack} validate={validate} />
      <TryPanel pack={pack} />
      {help && <FormulaHelp onClose={() => setHelp(false)} />}
      <div className="sk-sticky">
        {problems === null ? (
          <span className="sk-hint">{t("rules.checking")}</span>
        ) : problems.length > 0 ? (
          <details>
            <summary className="sk-invalid">{t("rules.problems", { n: String(problems.length) })}</summary>
            <ul className="sk-problems">
              {problems.slice(0, 50).map((p, i) => {
                const where = describePath(t, pack, p.path ?? "");
                return (
                  <li key={i}>
                    {where && <span className="sk-hint">{t("rules.problem_where", { where })}</span>}
                    {translateCode(lang, p.code, p.params)}
                  </li>
                );
              })}
            </ul>
          </details>
        ) : (
          <span>{t("rules.valid")}</span>
        )}
        <span className="sk-hint">{dirty ? t("rules.unsaved") : draftAt ? t("rules.draft_saved", { time: when(draftAt) }) : ""}</span>
        <button disabled={act.busy} onClick={() => void act.run(() => saveDraft(pack))}>
          {t("rules.save_draft")}
        </button>
        <button className="sk-primary" disabled={act.busy || problems === null || problems.length > 0} onClick={save}>
          {t("rules.save_version")}
        </button>
        <button className="sk-link" onClick={() => setHelp((x) => !x)}>
          {t("fh.open")}
        </button>
        <ErrorBox error={act.error ?? draftError ?? checkError} />
      </div>
      </Section>
    </div>
  );
}
