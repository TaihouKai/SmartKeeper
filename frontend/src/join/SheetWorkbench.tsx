import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { toCode } from "../ui/effectsCode";
import { api, call, type Schemas } from "../api/client";
import { useI18n } from "../i18n";
import { numberOptions, withUnit } from "../ui/choices";
import { Mover, moved } from "../ui/components";
import { EntryEditor, FieldInput, fieldLabel, rangeText, type Entry } from "../ui/EntryEditor";
import { translateCode } from "../ui/errors";
import { Described } from "../ui/markdown";

type Template = Schemas["EntityTemplate"];
type Field = Schemas["FieldDef"];
type Group = Schemas["GroupDef"];
type Preview = Schemas["PreviewOut"];
type Value = string | number | boolean;
/** preset_fields：固定条目里规则包留空的列（分组 -> 固定条目名 -> 列 -> 值），由玩家填。 */
export type SheetDraft = { name: string; fields: Record<string, Value>; groups: Record<string, Entry[]>; preset_fields?: Record<string, Record<string, Record<string, Value>>> };

type Section = { key: string; label: string; missing: number };

const empty = (v: Value | undefined) => v === undefined || v === "";
const isIdentity = (f: Field) => f.kind === "text" || f.kind === "boolean";
const isPlayer = (f: Field) => (f.cls ?? "player") === "player";
/** 必填而且还没填（有默认值的、是/否的不算）。 */
const missingField = (f: Field, v: Value | undefined) => f.required !== false && !f.initial && f.kind !== "boolean" && empty(v);

/** 一张角色卡的工作台：左边是几节（身份、数值、各个分组、检查），右边一次只显示一节；条目在侧栏里编辑。 */
export function SheetWorkbench({
  template,
  value,
  onChange,
  params,
  checks,
  onStatus,
  extra,
}: {
  template: Template;
  value: SheetDraft;
  onChange: (s: SheetDraft) => void;
  params: readonly Schemas["PackParam"][];
  checks: readonly string[];
  /** 这张卡还缺几处（标签上显示） */
  onStatus: (missing: number) => void;
  /** 身份一节最后放的东西（例如“删除这张卡”） */
  extra?: React.ReactNode;
}) {
  const { t, lang } = useI18n();
  const [preview, setPreview] = useState<Preview | null>(null);
  const [current, setCurrent] = useState("identity");
  const body = useMemo(() => JSON.stringify(value), [value]);
  useEffect(() => {
    const id = window.setTimeout(() => {
      call(api.POST("/api/character/preview", { body: { template: template.name, sheet: JSON.parse(body) } }))
        .then(setPreview)
        .catch(() => setPreview(null));
    }, 500);
    return () => window.clearTimeout(id);
  }, [body, template.name]);

  const fields = (template.fields ?? []).filter(isPlayer);
  const identity = fields.filter(isIdentity);
  const numbers = fields.filter((f) => !isIdentity(f));
  const groups = (template.groups ?? []).filter((g) => {
    const fixed = preview?.presets?.[g.name] ?? [];
    const mine = value.groups[g.name] ?? [];
    return !g.hidden && !(fixed.length === 0 && mine.length === 0 && g.max_count === 0);
  });
  const problems = preview?.derived.length ? preview.problems : [];
  const inGroup = (g: Group) => problems.filter((p) => (p.path ?? "").startsWith(`groups.${g.name}`)).length;

  const sections: Section[] = [
    { key: "identity", label: t("cf.identity"), missing: (value.name.trim() ? 0 : 1) + identity.filter((f) => missingField(f, value.fields[f.name])).length },
    { key: "numbers", label: t("cf.numbers"), missing: numbers.filter((f) => missingField(f, value.fields[f.name])).length },
    ...groups.map((g) => {
      const mine = value.groups[g.name] ?? [];
      const fixed = preview?.presets?.[g.name] ?? [];
      const openMissing = fixed.reduce((n, pname) => {
        const p = (g.presets ?? []).find((x) => x.name === pname);
        const filled = value.preset_fields?.[g.name]?.[pname] ?? {};
        return n + (g.fields ?? []).filter((c) => c.cls !== "runtime" && p && !(c.name in (p.fields ?? {})) && missingField(c, filled[c.name])).length;
      }, 0);
      return { key: `group:${g.name}`, label: g.label || g.name, missing: inGroup(g) + Math.max(0, (g.min_count ?? 0) - mine.length) + openMissing };
    }),
  ];
  const total = sections.reduce((n, s) => n + s.missing, 0) + problems.filter((p) => !(p.path ?? "").startsWith("groups.")).length;
  sections.push({ key: "review", label: t("cf.review"), missing: 0 });
  useEffect(() => onStatus(total), [total, onStatus]);

  const idx = Math.max(0, sections.findIndex((s) => s.key === current));
  const sec = sections[idx]!;
  const setField = (name: string, v: Value) => onChange({ ...value, fields: { ...value.fields, [name]: v } });
  const group = sec.key.startsWith("group:") ? groups.find((g) => `group:${g.name}` === sec.key) : undefined;

  return (
    <div className="cf">
      <nav className="cf-nav" aria-label={t("cf.sections")}>
        {sections.map((s) => (
          <button key={s.key} type="button" className={s.key === sec.key ? "active" : ""} onClick={() => setCurrent(s.key)}>
            <span>{s.label}</span>
            {s.key !== "review" && (s.missing > 0 ? <span className="cf-badge">{s.missing}</span> : <span className="cf-ok">✓</span>)}
          </button>
        ))}
      </nav>
      <section className="cf-main">
        <h2>{sec.label}</h2>
        {sec.key === "identity" && (
          <>
            <Described text={template.description} className="cf-lead" />
            <FieldRow label={template.name_label || t("character.name")} required missing={!value.name.trim()} desc={template.name_hint || t("character.name_hint")}>
              {(id) => <input id={id} value={value.name} onChange={(e) => onChange({ ...value, name: e.target.value })} />}
            </FieldRow>
            {identity.map((f) =>
              f.kind === "boolean" ? (
                <div key={f.name} className="cf-row">
                  <label className="cf-check">
                    <FieldInput def={f} value={value.fields[f.name]} onChange={(v) => setField(f.name, v)} />
                    <span className="cf-label">{fieldLabel(f, t("character.unnamed_field"))}</span>
                  </label>
                  <Described text={f.description} className="cf-desc" />
                </div>
              ) : (
              <FieldRow key={f.name} label={fieldLabel(f, t("character.unnamed_field"))} required={f.required !== false} missing={missingField(f, value.fields[f.name])} desc={f.name === template.appearance_field ? `${t("character.appearance_hint")} ${f.description ?? ""}` : f.description}>
                {(id) => <FieldInput id={id} def={f} value={value.fields[f.name]} onChange={(v) => setField(f.name, v)} />}
              </FieldRow>
              ),
            )}
            {extra}
          </>
        )}
        {sec.key === "numbers" && (
          <div className="cf-grid">
            {numbers.map((f) => {
              const range = rangeText(f, preview?.ranges?.[f.name]);
              return (
                <div key={f.name} className={`cf-cell${missingField(f, value.fields[f.name]) ? " missing" : ""}`}>
                  <label>
                    <span className="cf-label-line">
                      <span className="cf-label">{fieldLabel(f, t("character.unnamed_field"))}</span>
                      {range && <span className="cf-range">{range}</span>}
                    </span>
                    <FieldInput def={f} value={value.fields[f.name]} range={preview?.ranges?.[f.name]} onChange={(v) => setField(f.name, v)} />
                  </label>
                  <Described text={f.description} className="cf-desc" />
                </div>
              );
            })}
          </div>
        )}
        {group && <GroupPanel key={group.name} template={template} g={group} value={value} onChange={onChange} preview={preview} params={params} checks={checks} />}
        {sec.key === "review" && <Review template={template} value={value} preview={preview} sections={sections} lang={lang} onGo={setCurrent} />}
        <div className="cf-pager">
          {idx > 0 ? (
            <button type="button" onClick={() => setCurrent(sections[idx - 1]!.key)}>
              ← {sections[idx - 1]!.label}
            </button>
          ) : (
            <span />
          )}
          {idx < sections.length - 1 && (
            <button type="button" onClick={() => setCurrent(sections[idx + 1]!.key)}>
              {sections[idx + 1]!.label} →
            </button>
          )}
        </div>
      </section>
      <Stats template={template} preview={preview} />
    </div>
  );
}

/** 一个字段：标签（必填的在标签外面标星，没填的输入框标红）、输入、一行说明。 */
function FieldRow({ label, required, missing, desc, children }: { label: string; required?: boolean; missing?: boolean; desc?: string | null; children: (id: string) => React.ReactNode }) {
  const id = useId();
  return (
    <div className={`cf-row${missing ? " missing" : ""}`}>
      <div className="cf-label-line">
        <label htmlFor={id} className="cf-label">
          {label}
        </label>
        {required && (
          <span className="cf-req" aria-hidden="true">
            *
          </span>
        )}
      </div>
      {children(id)}
      <Described text={desc} className="cf-desc" />
    </div>
  );
}

/** 右边的数值速览：按现在的填写算出来的生命值、魔力值等。 */
function Stats({ template, preview }: { template: Template; preview: Preview | null }) {
  const { t } = useI18n();
  const labels = new Map<string, string>([...(template.derived ?? []).map((d) => [d.name, d.label || d.name] as const), ...(template.fields ?? []).map((f) => [f.name, f.label || f.name] as const)]);
  const units = new Map<string, string | null | undefined>([...(template.derived ?? []).map((d) => [d.name, d.unit] as const), ...(template.fields ?? []).map((f) => [f.name, f.unit] as const)]);
  const shown = (preview?.derived ?? []).filter((d) => labels.has(d.name));
  return (
    <aside className="cf-side">
      <strong>{t("cf.stats")}</strong>
      {shown.length === 0 ? (
        <p className="sk-hint">{t("cf.stats_empty")}</p>
      ) : (
        <dl>
          {shown.map((d) => (
            <div key={d.name}>
              <dt>{labels.get(d.name)}</dt>
              <dd>{withUnit(d.value, units.get(d.name))}</dd>
            </div>
          ))}
        </dl>
      )}
    </aside>
  );
}

/** 一个分组：自动获得的条目（一行一个，要自己填的列就在这一行填）和自己写的条目（一行一个，点“编辑”在侧栏里改）。 */
function GroupPanel({ template, g, value, onChange, preview, params, checks }: { template: Template; g: Group; value: SheetDraft; onChange: (s: SheetDraft) => void; preview: Preview | null; params: readonly Schemas["PackParam"][]; checks: readonly string[] }) {
  const { t } = useI18n();
  const [editing, setEditing] = useState<number | null>(null);
  const [viewing, setViewing] = useState<string | null>(null);
  const entries = value.groups[g.name] ?? [];
  const setEntries = (es: Entry[]) => onChange({ ...value, groups: { ...value.groups, [g.name]: es } });
  const fixed = preview?.presets?.[g.name] ?? [];
  const canAdd = g.max_count === null || g.max_count === undefined || entries.length < g.max_count;
  const cols = g.fields ?? [];
  const derived = [...(template.derived ?? []).map((d) => d.name), ...(template.fields ?? []).filter((f) => isPlayer(f) && (f.kind === "number" || f.kind === "boolean")).map((f) => f.name)];
  const validate = useCallback(
    (formula: string, inEntry: string, scope?: "dice" | "script" | "config" | "bonus", other?: string, names?: string[]) =>
      call(api.POST("/api/formula/validate", { body: { formula, template: template.name, in_entry: inEntry, dice: scope === "dice", script: scope === "script", config: scope === "config", bonus: scope === "bonus", other: other ?? "", names: names ?? [] } })),
    [template.name],
  );
  const add = (e: Entry) => {
    setEntries([...entries, e]);
    setEditing(entries.length);
  };
  const copyOf = (p: Schemas["GroupPreset"]): Entry => ({
    name: "",
    id: "",
    description: p.description ?? "",
    fields: { ...(p.fields ?? {}) } as Entry["fields"],
    effects: [],
    bonus: p.bonus || toCode(p.effects ?? []),
    config: p.config ?? "",
    script: p.script ?? "",
    params: p.params ?? [],
    uses: (p.uses ?? []) as unknown as Entry["uses"],
  });
  const badges = (fieldsOf: Record<string, unknown>) =>
    cols
      .filter((c) => c.cls !== "runtime" && fieldsOf[c.name] !== undefined && fieldsOf[c.name] !== "")
      .slice(0, 3)
      .map((c) => {
        const v = fieldsOf[c.name];
        const named = typeof v === "number" ? numberOptions(c.choices ?? []).find((o) => o.value === v)?.label : undefined;
        return `${c.label || c.name} ${named ?? String(v)}`;
      });
  const edited = editing !== null ? entries[editing] : undefined;
  return (
    <>
      <Described text={g.description} className="cf-lead" />
      {fixed.length > 0 && (
        <>
          <h3 className="cf-sub">{t("cf.auto")}</h3>
          <ul className="cf-list">
            {fixed.map((pname) => {
              const p = (g.presets ?? []).find((x) => x.name === pname);
              const open = p ? cols.filter((c) => c.cls !== "runtime" && !(c.name in (p.fields ?? {}))) : [];
              const mine = value.preset_fields?.[g.name]?.[pname] ?? {};
              const set = (col: string, v: Value) => onChange({ ...value, preset_fields: { ...value.preset_fields, [g.name]: { ...value.preset_fields?.[g.name], [pname]: { ...mine, [col]: v } } } });
              return (
                <li key={pname} className="cf-item">
                  <div className="cf-item-main">
                    <strong>{pname}</strong>
                    {p?.id && <RefTag template={template.name} id={p.id} />}
                    {p && badges(p.fields ?? {}).map((b) => (
                      <span key={b} className="cf-tag">
                        {b}
                      </span>
                    ))}
                    <Clamp text={p?.description ?? ""} />
                  </div>
                  <div className="cf-item-actions">
                    <button type="button" onClick={() => setViewing(pname)}>
                      {t("cf.view")}
                    </button>
                  </div>
                  {open.length > 0 && (
                    <div className="cf-item-fill">
                      {open.map((c) => (
                        <label key={c.name} className={missingField(c, mine[c.name]) ? "missing" : ""}>
                          <span className="cf-label">{fieldLabel(c, t("character.unnamed_field"))}</span>
                          <FieldInput def={c} value={mine[c.name]} onChange={(v) => set(c.name, v)} />
                        </label>
                      ))}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </>
      )}
      {(canAdd || entries.length > 0) && (
        <>
          <h3 className="cf-sub">{t("cf.yours")}</h3>
          {entries.length === 0 && <p className="sk-hint">{t("cf.none_yet")}</p>}
          <ul className="cf-list">
            {entries.map((en, i) => (
              <li key={i} className="cf-item">
                <div className="cf-item-main">
                  <strong>{en.name || t("cf.unnamed")}</strong>
                  {en.id && <RefTag template={template.name} id={en.id} />}
                  {badges(en.fields).map((b) => (
                    <span key={b} className="cf-tag">
                      {b}
                    </span>
                  ))}
                  {(en.uses ?? []).length > 0 && <span className="cf-tag">{t("cf.uses_n", { n: String((en.uses ?? []).length) })}</span>}
                  <Clamp text={en.description} />
                </div>
                <div className="cf-item-actions">
                  <button type="button" onClick={() => setEditing(i)}>
                    {t("cf.edit")}
                  </button>
                  <Mover index={i} count={entries.length} onMove={(from, to) => setEntries(moved(entries, from, to))} />
                  <button type="button" className="sk-link wb-danger" onClick={() => setEntries(entries.filter((_, j) => j !== i))}>
                    {t("common.remove")}
                  </button>
                </div>
              </li>
            ))}
          </ul>
          {canAdd && (
            <div className="sk-row">
              <button type="button" className="sk-primary" onClick={() => add({ name: "", id: "", description: "", fields: {}, effects: [] })}>
                + {t("character.add_entry")}
              </button>
              {(g.presets ?? []).length > 0 && (
                <select value="" onChange={(e) => e.target.value !== "" && add(copyOf((g.presets ?? [])[Number(e.target.value)]!))}>
                  <option value="">{t("character.copy_preset")}</option>
                  {(g.presets ?? []).map((p, k) => (
                    <option key={k} value={String(k)}>
                      {p.name}
                    </option>
                  ))}
                </select>
              )}
            </div>
          )}
        </>
      )}
      {viewing !== null && (g.presets ?? []).some((x) => x.name === viewing) && (
        <PresetView
          template={template.name}
          p={(g.presets ?? []).find((x) => x.name === viewing)!}
          g={g}
          defaults={params.filter((x) => (x.groups ?? []).includes(g.name))}
          canCopy={canAdd}
          onCopy={(p) => {
            setViewing(null);
            add(copyOf(p));
          }}
          onClose={() => setViewing(null)}
        />
      )}
      {edited && editing !== null && (
        <aside key={editing} className="sk-drawer cf-drawer" aria-label={t("cf.edit")}>
          <div className="sk-drawer-head">
            <h3>{edited.name || t("cf.unnamed")}</h3>
            <button type="button" className="sk-primary" onClick={() => setEditing(null)}>
              {t("cf.done")}
            </button>
          </div>
          <EntryEditor
            group={g}
            derived={derived}
            entry={edited}
            validate={validate}
            simple
            defaults={params.filter((x) => (x.groups ?? []).includes(g.name))}
            checks={checks}
            spendTargets={(template.fields ?? []).filter((f) => f.kind === "number" || f.kind === "resource").map((f) => f.name)}
            onChange={(e) => setEntries(entries.map((x, j) => (j === editing ? e : x)))}
          />
        </aside>
      )}
    </>
  );
}

/** 规则包写好的条目的细节（只读）：说明、列、常驻加成、怎么用、生效时发生什么、参数、用途。可以照着写一条。 */
/** 条目的引用名（<模板>.<条目ID>）：公式和脚本里用它引用这一条；点一下整段选中，方便复制。 */
function RefTag({ template, id }: { template: string; id: string }) {
  const { t } = useI18n();
  return (
    <code className="cf-ref" title={t("cf.ref_hint")}>
      {template}.{id}
    </code>
  );
}

function PresetView({ template, p, g, defaults, canCopy, onCopy, onClose }: { template: string; p: Schemas["GroupPreset"]; g: Group; defaults: readonly Schemas["PackParam"][]; canCopy: boolean; onCopy: (p: Schemas["GroupPreset"]) => void; onClose: () => void }) {
  const { t } = useI18n();
  const cols = (g.fields ?? []).filter((c) => (p.fields ?? {})[c.name] !== undefined);
  const params = [...defaults, ...(p.params ?? [])];
  const code = (title: string, text: string | undefined) =>
    text && text.trim() ? (
      <>
        <h4>{title}</h4>
        <pre className="sk-code">{text.trim()}</pre>
      </>
    ) : null;
  return (
    <aside className="sk-drawer cf-drawer" aria-label={p.name}>
      <div className="sk-drawer-head">
        <h3>{p.name}</h3>
        <span className="sk-row">
          {canCopy && (
            <button type="button" className="sk-primary" onClick={() => onCopy(p)}>
              {t("cf.copy_this")}
            </button>
          )}
          <button type="button" className="sk-link" onClick={onClose}>
            {t("play.close")}
          </button>
        </span>
      </div>
      {p.id && (
        <p className="sk-hint">
          {t("cf.ref")} <RefTag template={template} id={p.id} />
        </p>
      )}
      <Described text={p.description} className="cf-lead" />
      {!p.config?.trim() && !p.script?.trim() && (p.uses ?? []).length === 0 && <p className="sk-hint">{t("rules.uses.kp_rules")}</p>}
      {cols.length > 0 && (
        <p>
          {cols.map((c) => (
            <span key={c.name} className="cf-tag">
              {c.label || c.name} {String((p.fields ?? {})[c.name])}
            </span>
          ))}
        </p>
      )}
      {code(t("character.config_simple"), p.config)}
      {code(t("character.effects_simple"), p.bonus || toCode(p.effects ?? []))}
      {code(t("character.script_simple"), p.script)}
      {params.length > 0 && (
        <>
          <h4>{t("cf.params")}</h4>
          <ul>
            {params.map((x) => (
              <li key={x.name}>
                <strong>{x.label || x.name}</strong>
                {x.by_kp && <span className="cf-tag">{t("params.by_kp")}</span>}
                {(x.choices ?? []).length > 0 && <span className="sk-hint">（{(x.choices ?? []).join("、")}）</span>}
                <Described text={x.description} />
              </li>
            ))}
          </ul>
        </>
      )}
      {(p.uses ?? []).map((u) => (
        <div key={u.name}>
          <h4>
            {t("rules.uses.title")}：{u.name}
          </h4>
          <Described text={u.description} />
          {code(t("character.config_simple"), u.config)}
          {code(t("uses.effects"), u.bonus || toCode(u.effects ?? []))}
          {code(t("character.script_simple"), u.script)}
        </div>
      ))}
    </aside>
  );
}

/** 长说明先显示两行，点了展开。 */
function Clamp({ text }: { text: string }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  // 真的被截掉了才给“展开”：量收起时的高度，宽度变了再量
  const [long, setLong] = useState(false);
  const box = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const el = box.current?.firstElementChild as HTMLElement | null | undefined;
    if (!el || open) return;
    const measure = () => setLong(el.scrollHeight > el.clientHeight + 1);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [text, open]);
  if (!text.trim()) return null;
  return (
    <span ref={box} className={`cf-clamp${open ? " open" : ""}`}>
      <Described text={text} className="" />
      {long && (
        <button type="button" className="sk-link" onClick={() => setOpen(!open)}>
          {t(open ? "cf.less" : "cf.more")}
        </button>
      )}
    </span>
  );
}

/** 检查：还缺什么、哪里不对（点了跳到那一节）。 */
function Review({ template, value, preview, sections, lang, onGo }: { template: Template; value: SheetDraft; preview: Preview | null; sections: Section[]; lang: string; onGo: (key: string) => void }) {
  const { t } = useI18n();
  const todo = sections.filter((s) => s.missing > 0);
  const problems = preview?.derived.length ? preview.problems : [];
  return (
    <>
      <p className="cf-lead">{t("cf.review_lead", { name: value.name || template.label || template.name })}</p>
      {todo.length === 0 && problems.length === 0 ? (
        <p className="cf-good">✓ {t("cf.complete")}</p>
      ) : (
        <ul className="cf-todo">
          {todo.map((s) => (
            <li key={s.key}>
              <button type="button" className="sk-link" onClick={() => onGo(s.key)}>
                {s.label}
              </button>
              ：{t("cf.missing", { n: String(s.missing) })}
            </li>
          ))}
          {problems.map((p, i) => (
            <li key={i}>{translateCode(lang as "zh" | "en", p.code, p.params)}</li>
          ))}
        </ul>
      )}
      {preview && preview.derived.length === 0 && <p className="sk-hint">{t("character.preview_incomplete")}</p>}
    </>
  );
}
