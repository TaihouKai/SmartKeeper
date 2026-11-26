import { useCallback, useEffect, useRef, useState } from "react";
import { api, call, type Schemas } from "../api/client";
import { useI18n } from "../i18n";
import { ErrorBox } from "../ui/components";
import { SheetWorkbench, type SheetDraft } from "./SheetWorkbench";
import { useDocsPackNames, type PackName } from "../ui/docs";
import { LibraryBox, initialSave, saveToLibrary, type LibrarySave, type Origin } from "./Library";

export type { SheetDraft } from "./SheetWorkbench";

type Template = Schemas["EntityTemplate"];
type Value = string | number | boolean;
export type Submission = { template: string; sheet: SheetDraft };

const dropEmpty = (o: Record<string, Value>) => Object.fromEntries(Object.entries(o).filter(([, v]) => v !== ""));

function emptySheet(): SheetDraft {
  return { name: "", fields: {}, groups: {} };
}

/** 建角时要创建的实体：按规则包的 player_entities，每个模板先放最少数量。 */
/** 语法手册里“这套规则的名字”：字段和推导值写 self.<名字>，参数写 this.<名字>，检定写 "名字"。 */
function packNames(templates: Template[], params: readonly Schemas["PackParam"][], checks: readonly string[], t: (k: string) => string): PackName[] {
  const out: PackName[] = [];
  const seen = new Set<string>();
  const push = (p: PackName) => {
    if (seen.has(p.kind + p.sig)) return;
    seen.add(p.kind + p.sig);
    // 说明里的规则书引用 [[标题]] 只留标题
    out.push({ ...p, text: p.text.replace(/\[\[(.+?)\]\]/g, "$1") });
  };
  for (const tp of templates) {
    const who = tp.label || tp.name;
    for (const f of tp.fields ?? []) push({ name: f.name, sig: `self.${f.name}`, text: [f.label, f.description, `(${who})`].filter(Boolean).join(" "), kind: t("docs.kind.field") });
    for (const d of tp.derived ?? []) push({ name: d.name, sig: `self.${d.name}`, text: [d.label, `= ${d.formula}`, `(${who})`].filter(Boolean).join(" "), kind: t("docs.kind.derived") });
    for (const g of tp.groups ?? []) push({ name: g.name, sig: `count(self.${g.name}.${(g.fields ?? [])[0]?.name ?? "level"}, 1)`, text: [g.label, `(${who})`].filter(Boolean).join(" "), kind: t("docs.kind.group") });
  }
  for (const p of params) push({ name: p.name, sig: `this.${p.name}`, text: [p.label, p.description, (p.choices ?? []).join("、")].filter(Boolean).join(" "), kind: t("docs.kind.param") });
  for (const c of checks) push({ name: c, sig: `check = "${c}"`, text: "", kind: t("docs.kind.check") });
  return out;
}

export function initialSubmissions(playerEntities: { template: string; min: number; max: number }[]): Submission[] {
  return playerEntities.flatMap((pe) => Array.from({ length: Math.max(pe.min, 1) }, () => ({ template: pe.template, sheet: emptySheet() })));
}

/** 建卡：上面是每张卡一个标签，中间是这张卡的工作台，底下一条固定的栏（自动保存、还缺几处、提交）。 */
export function CharacterForm({
  templates,
  playerEntities,
  onSubmitted,
  params = [],
  checks = [],
  origin = null,
  onOrigin,
  onPickAnother,
}: {
  templates: Template[];
  playerEntities: { template: string; min: number; max: number }[];
  onSubmitted: () => void;
  /** 从角色库载入的角色（提交时可以更新它） */
  origin?: Origin | null;
  /** 存进角色库以后：现在编辑的是角色库里的这个角色（之后接着更新它） */
  onOrigin?: (o: Origin) => void;
  /** 回到“选角色” */
  onPickAnother?: () => void;
  /** 规则包的默认参数和检定名（自己加参数时用） */
  params?: readonly Schemas["PackParam"][];
  checks?: readonly string[];
}) {
  const { t } = useI18n();
  // 语法手册里列出这套规则的名字：各角色卡的字段、推导值、分组，检定，参数
  useDocsPackNames(packNames(templates, params, checks, t));
  const [subs, setSubs] = useState<Submission[]>(() => initialSubmissions(playerEntities));
  const [tab, setTab] = useState(0);
  const [missing, setMissing] = useState<Record<number, number>>({});
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [libSave, setLibSave] = useState<LibrarySave>(() => initialSave(origin));
  const [libError, setLibError] = useState<unknown>(null);
  const [libBusy, setLibBusy] = useState(false);
  const [libSavedAt, setLibSavedAt] = useState<string | null>(null);
  // 正在编辑的角色换了（例如刷新以后才认出来是哪个）：角色库的设置跟着换
  const originId = origin?.id;
  useEffect(() => setLibSave(initialSave(origin)), [originId]); // eslint-disable-line react-hooks/exhaustive-deps
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
  const statusOf = useCallback((i: number) => (n: number) => setMissing((m) => (m[i] === n ? m : { ...m, [i]: n })), []);
  const cleanSubs = (): Submission[] =>
    subs.map((s) => ({
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
  // 按角色库的设置存一次；存成新角色以后接着更新它
  const saveLib = async (clean: Submission[]) => {
    setLibError(null);
    const saved = await saveToLibrary(clean, origin, libSave);
    if (saved) {
      onOrigin?.(saved);
      setLibSave((v) => ({ ...v, mode: "update", name: saved.name, password: "", newPassword: "", current: "" }));
      setLibSavedAt(new Date().toISOString());
    }
  };
  const saveLibNow = async () => {
    setLibBusy(true);
    try {
      await saveLib(cleanSubs());
    } catch (e) {
      setLibError(e);
    } finally {
      setLibBusy(false);
    }
  };
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await saveNow(subs).catch(() => undefined);
      const clean = cleanSubs();
      await call(api.POST("/api/character", { body: { sheets: clean as never } }));
      // 交给这一局以后再存进角色库；存失败（例如密码不对）不影响已经提交的
      try {
        await saveLib(clean);
      } catch (e) {
        setLibError(e);
        return;
      }
      onSubmitted();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  if (!loaded) return <p>{t("common.loading")}</p>;
  const current = Math.min(tab, subs.length - 1);
  const count = (name: string) => subs.filter((s) => s.template === name).length;
  const limit = (name: string) => playerEntities.find((pe) => pe.template === name);
  const totalMissing = subs.reduce((n, _s, i) => n + (missing[i] ?? 0), 0);
  return (
    <div className="cf-wrap">
      <div className="cf-tabs" role="tablist">
        {subs.map((s, i) => {
          const tp = templates.find((x) => x.name === s.template);
          return (
            <button key={i} type="button" role="tab" aria-selected={i === current} className={i === current ? "active" : ""} onClick={() => setTab(i)}>
              <span>{tp?.label || s.template}</span>
              {s.sheet.name && <span className="cf-tab-name">{s.sheet.name}</span>}
              {(missing[i] ?? 0) > 0 ? <span className="cf-badge">{missing[i]}</span> : <span className="cf-ok">✓</span>}
            </button>
          );
        })}
        {playerEntities
          .filter((pe) => count(pe.template) < pe.max)
          .map((pe) => (
            <button key={pe.template} type="button" className="cf-tab-add" onClick={() => {
              setSubs([...subs, { template: pe.template, sheet: emptySheet() }]);
              setTab(subs.length);
            }}>
              + {templates.find((x) => x.name === pe.template)?.label || pe.template}
            </button>
          ))}
      </div>
      {/* 每张卡都挂着（只显示当前这张），这样没打开过的卡也能算出还缺几处 */}
      {subs.map((s, i) => {
        const tp = templates.find((x) => x.name === s.template);
        if (!tp) return null;
        return (
          <div key={i} hidden={i !== current}>
            <SheetWorkbench
              template={tp}
              value={s.sheet}
              params={params}
              checks={checks}
              onStatus={statusOf(i)}
              onChange={(sheet) => setSubs(subs.map((x, j) => (j === i ? { ...x, sheet } : x)))}
              extra={
                count(s.template) > (limit(s.template)?.min ?? 1) ? (
                  <button type="button" className="sk-link wb-danger" onClick={() => {
                    setSubs(subs.filter((_, j) => j !== i));
                    setMissing({});
                    setTab(0);
                  }}>
                    {t("cf.remove_sheet")}
                  </button>
                ) : null
              }
            />
          </div>
        );
      })}
      {onPickAnother && (
        <p className="sk-hint">
          {origin ? t("lib.loaded", { name: origin.name }) : ""}{" "}
          <button type="button" className="sk-link" onClick={onPickAnother}>
            {t("lib.pick_another")}
          </button>
        </p>
      )}
      <LibraryBox origin={origin} value={libSave} onChange={setLibSave} onSaveNow={() => void saveLibNow()} busy={libBusy} savedAt={libSavedAt} />
      <ErrorBox error={libError} />
      <div className="cf-footer">
        <span className="sk-hint">{saveError ? t("cf.save_failed") : savedAt ? t("character.autosaved", { time: new Date(savedAt).toLocaleTimeString() }) : ""}</span>
        <span className={totalMissing > 0 ? "cf-footer-todo" : "cf-footer-ok"}>{totalMissing > 0 ? t("cf.missing", { n: String(totalMissing) }) : t("cf.complete")}</span>
        <button className="sk-primary" disabled={busy} onClick={() => void submit()}>
          {t("character.submit")}
        </button>
      </div>
      <ErrorBox error={error} />
    </div>
  );
}
