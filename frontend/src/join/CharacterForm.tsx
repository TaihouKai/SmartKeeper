import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, call, type Schemas } from "../api/client";
import { useI18n } from "../i18n";
import { ErrorBox, Mover, moved } from "../ui/components";
import { EntryEditor, FieldInput, fieldLabel, rangeText, type Entry } from "../ui/EntryEditor";
import { translateCode } from "../ui/errors";
import { Described } from "../ui/markdown";

type Template = Schemas["EntityTemplate"];
type Value = string | number | boolean;
/** preset_fields：固定条目里规则包留空的列（分组 -> 固定条目名 -> 列 -> 值），由玩家填。 */
export type SheetDraft = { name: string; fields: Record<string, Value>; groups: Record<string, Entry[]>; preset_fields?: Record<string, Record<string, Record<string, Value>>> };

const dropEmpty = (o: Record<string, Value>) => Object.fromEntries(Object.entries(o).filter(([, v]) => v !== ""));
export type Submission = { template: string; sheet: SheetDraft };

function emptySheet(): SheetDraft {
  return { name: "", fields: {}, groups: {} };
}

/** 建角时要创建的实体：按规则包的 player_entities，每个模板先放最少数量。 */
export function initialSubmissions(playerEntities: { template: string; min: number; max: number }[]): Submission[] {
  return playerEntities.flatMap((pe) => Array.from({ length: Math.max(pe.min, 1) }, () => ({ template: pe.template, sheet: emptySheet() })));
}

/** 一张角色卡：按模板生成表单，实时试算推导值。 */
export function SheetEditor({ template, value, onChange, params = [], checks = [] }: { template: Template; value: SheetDraft; onChange: (s: SheetDraft) => void; params?: readonly Schemas["PackParam"][]; checks?: readonly string[] }) {
  const { t, lang } = useI18n();
  const [preview, setPreview] = useState<Schemas["PreviewOut"] | null>(null);
  const fields = (template.fields ?? []).filter((f) => f.cls !== "runtime");
  // 修正能作用的数值：推导值，和建角时填的数值、是/否字段
  const derived = [
    ...(template.derived ?? []).map((d) => d.name),
    ...(template.fields ?? []).filter((f) => (f.cls ?? "player") === "player" && (f.kind === "number" || f.kind === "boolean")).map((f) => f.name),
  ];
  const validate = useCallback(
    (formula: string, inEntry: string, scope?: "dice" | "script" | "config", other?: string, names?: string[]) =>
      call(api.POST("/api/formula/validate", { body: { formula, template: template.name, in_entry: inEntry, dice: scope === "dice", script: scope === "script", config: scope === "config", other: other ?? "", names: names ?? [] } })),
    [template.name],
  );
  const spendTargets = (template.fields ?? []).filter((f) => f.kind === "number" || f.kind === "resource").map((f) => f.name);
  const topDice = useCallback(
    (formula: string) => call(api.POST("/api/formula/validate", { body: { formula, template: template.name, dice: true, script: false, config: false, other: "", names: [] } })),
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
      <Described text={template.description} className="sk-template-desc" />
      <label>
        {t("character.name")}
        <input value={value.name} onChange={(e) => onChange({ ...value, name: e.target.value })} />
      </label>
      {fields.map((f) => (
        <label key={f.name}>
          {fieldLabel(f, t("character.unnamed_field"))}
          {rangeText(f) && <span className="sk-range"> {t("character.range", { range: rangeText(f) })}</span>}
          {f.name === template.appearance_field && <small> {t("character.appearance_hint")}</small>}
          <Described text={f.description} />
          <FieldInput def={f} value={value.fields[f.name]} validateFormula={topDice} onChange={(v) => onChange({ ...value, fields: { ...value.fields, [f.name]: v } })} />
        </label>
      ))}
      {(template.groups ?? []).map((g) => {
        const entries = value.groups[g.name] ?? [];
        const setEntries = (es: Entry[]) => onChange({ ...value, groups: { ...value.groups, [g.name]: es } });
        const fixed = preview?.presets?.[g.name] ?? [];
        const canAdd = g.max_count === null || g.max_count === undefined || entries.length < g.max_count;
        // 玩家不能写、也没有自动获得的条目的分组不显示（例如还没满足条件的固定条目）
        if (g.hidden || (!fixed.length && !entries.length && g.max_count === 0)) return null;
        return (
          <fieldset key={g.name}>
            <legend>{g.label || g.name}</legend>
            <Described text={g.description} />
            {fixed.length > 0 && <p className="sk-hint">{t("character.fixed_entries_head")}</p>}
            {fixed.map((pname) => {
              // 自动获得的条目：名字和说明；规则包留空的列由玩家填（例如这个角色的对魔力等级）
              const p = (g.presets ?? []).find((x) => x.name === pname);
              const open = p ? (g.fields ?? []).filter((x) => x.cls !== "runtime" && !(x.name in (p.fields ?? {}))) : [];
              const mine = value.preset_fields?.[g.name]?.[pname] ?? {};
              const set = (col: string, v: Value) =>
                onChange({
                  ...value,
                  preset_fields: { ...value.preset_fields, [g.name]: { ...value.preset_fields?.[g.name], [pname]: { ...mine, [col]: v } } },
                });
              return (
                <div key={pname} className="sk-preset-fill">
                  <strong>{pname}</strong>
                  <Described text={p?.description} />
                  {open.map((fd) => (
                    <label key={fd.name}>
                      {fieldLabel(fd, t("character.unnamed_field"))}
                      {rangeText(fd) && <span className="sk-range"> {t("character.range", { range: rangeText(fd) })}</span>}
                      <Described text={fd.description} />
                      <FieldInput def={fd} value={mine[fd.name]} validateFormula={topDice} onChange={(v) => set(fd.name, v)} />
                    </label>
                  ))}
                </div>
              );
            })}
            {entries.map((en, i) => (
              <EntryEditor
                key={i}
                group={g}
                derived={derived}
                entry={en}
                validate={validate}
                simple
                defaults={params.filter((x) => (x.groups ?? []).includes(g.name))}
                checks={checks}
                spendTargets={spendTargets}
                onChange={(e) => setEntries(entries.map((x, j) => (j === i ? e : x)))}
                onRemove={() => setEntries(entries.filter((_, j) => j !== i))}
                mover={<Mover index={i} count={entries.length} onMove={(from, to) => setEntries(moved(entries, from, to))} />}
              />
            ))}
            {canAdd && (
              <button type="button" onClick={() => setEntries([...entries, { name: "", id: "", description: "", fields: {}, effects: [] }])}>
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
          {preview.derived.length === 0 && preview.problems.length > 0 ? (
            // 还没填完：算不出数值，不用把内部的错误代码给玩家看
            <p className="sk-hint">{t("character.preview_incomplete")}</p>
          ) : (
            preview.problems.length > 0 && (
              <ul className="sk-problems">
                {preview.problems.map((p, i) => (
                  <li key={i}>{translateCode(lang, p.code, p.params)}</li>
                ))}
              </ul>
            )
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
  params = [],
  checks = [],
}: {
  templates: Template[];
  playerEntities: { template: string; min: number; max: number }[];
  onSubmitted: () => void;
  /** 规则包的默认参数和检定名（自己加参数时用） */
  params?: readonly Schemas["PackParam"][];
  checks?: readonly string[];
}) {
  const { t } = useI18n();
  const [subs, setSubs] = useState<Submission[]>(() => initialSubmissions(playerEntities));
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  // 自动保存：打开时先取回服务器上的草稿（没有草稿但提交过的，从上次提交的内容接着改）
  const [loaded, setLoaded] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<unknown>(null);
  const lastSaved = useRef("");
  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const d = await call(api.GET("/api/character/draft"));
        if (!alive) return;
        if (Array.isArray(d.sheets) && d.sheets.length > 0) {
          setSubs(d.sheets as unknown as Submission[]);
          lastSaved.current = JSON.stringify(d.sheets);
          setSavedAt(d.updated_at ?? null);
        } else {
          const prev = await call(api.GET("/api/character"));
          if (alive && prev.length > 0) setSubs(prev.map((x) => ({ template: x.template, sheet: x.sheet as unknown as SheetDraft })));
        }
      } catch {
        // 取不到就从空白开始
      } finally {
        if (alive) setLoaded(true);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);
  const saveNow = useCallback(async (value: Submission[]) => {
    const text = JSON.stringify(value);
    if (text === lastSaved.current) return;
    const d = await call(api.PUT("/api/character/draft", { body: { sheets: value as never } }));
    lastSaved.current = text;
    setSavedAt(d.updated_at ?? null);
    setSaveError(null);
  }, []);
  // 停手 2 秒后自动存
  useEffect(() => {
    if (!loaded) return;
    const id = window.setTimeout(() => {
      saveNow(subs).catch((e: unknown) => setSaveError(e));
    }, 2000);
    return () => window.clearTimeout(id);
  }, [subs, loaded, saveNow]);
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await saveNow(subs).catch(() => undefined);
      const clean = subs.map((s) => ({
        template: s.template,
        sheet: {
          ...s.sheet,
          fields: dropEmpty(s.sheet.fields),
          preset_fields: Object.fromEntries(
            Object.entries(s.sheet.preset_fields ?? {}).map(([g, byName]) => [g, Object.fromEntries(Object.entries(byName).map(([n, vals]) => [n, dropEmpty(vals)]))]),
          ),
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
  if (!loaded) return <p>{t("common.loading")}</p>;
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
                <SheetEditor template={tpl} value={s.sheet} params={params} checks={checks} onChange={(sheet) => setSubs(subs.map((x, j) => (j === i ? { ...x, sheet } : x)))} />
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
      <ErrorBox error={saveError} />
      <button className="sk-primary" disabled={busy} onClick={() => void submit()}>
        {t("character.submit")}
      </button>
      {savedAt && <span className="sk-hint"> {t("character.autosaved", { time: new Date(savedAt).toLocaleTimeString() })}</span>}
    </div>
  );
}
