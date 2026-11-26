import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api, call, type Schemas } from "../api/client";
import { useI18n } from "../i18n";
import { ErrorBox } from "../ui/components";
import { SheetWorkbench, type SheetDraft } from "./SheetWorkbench";
import { useDocsPackNames, type PackName } from "../ui/docs";
import { LibraryBox, initialSave, saveToLibrary, type LibrarySave, type Origin } from "./Library";
import { FormBackendContext, gameBackend, type FormBackend } from "./formBackend";
import { CopilotContext, CopilotPanel, SheetIndexContext, entryName, type CopilotFocus, type CopilotTurn } from "./Copilot";
import type { Entry } from "../ui/EntryEditor";

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

/** 条目缺的部分补齐（从角色库、示例卡、助手来的条目可能没写说明、列）。 */
export function normalizeEntry(raw: unknown): Entry {
  const e = (raw && typeof raw === "object" ? raw : {}) as Partial<Entry>;
  return { ...e, name: e.name ?? "", description: e.description ?? "", fields: e.fields ?? {}, effects: e.effects ?? [] };
}

/** 一张卡缺的部分补齐：名字、字段、分组，每个条目也补齐。 */
export function normalizeSubmission(s: Submission): Submission {
  const sheet = (s.sheet ?? {}) as Partial<SheetDraft>;
  const groups = Object.fromEntries(Object.entries(sheet.groups ?? {}).map(([g, es]) => [g, (Array.isArray(es) ? es : []).map(normalizeEntry)]));
  return { template: s.template, sheet: { ...sheet, name: sheet.name ?? "", fields: sheet.fields ?? {}, groups } };
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
  backend = gameBackend,
  bookMode = false,
  autoFix = null,
}: {
  templates: Template[];
  playerEntities: { template: string; min: number; max: number }[];
  /** 提交给这一局以后（只在局里建卡时有） */
  onSubmitted?: () => void;
  /** 服务器接口：局里建卡（默认）或者在规则书下编辑角色库 */
  backend?: FormBackend;
  /** 在规则书下编辑角色库：没有“提交给这一局”，底下的按钮是存进角色库 */
  bookMode?: boolean;
  /** 从角色库载入的角色（提交时可以更新它） */
  origin?: Origin | null;
  /** 存进角色库以后：现在编辑的是角色库里的这个角色（之后接着更新它） */
  onOrigin?: (o: Origin) => void;
  /** 回到“选角色” */
  onPickAnother?: () => void;
  /** 规则包的默认参数和检定名（自己加参数时用） */
  params?: readonly Schemas["PackParam"][];
  checks?: readonly string[];
  /** 让建卡助手按这份审核意见自动改卡（key 变了再改一次） */
  autoFix?: { comments: string; key: number } | null;
}) {
  const { t, lang } = useI18n();
  // 语法手册里列出这套规则的名字：各角色卡的字段、推导值、分组，检定，参数
  useDocsPackNames(packNames(templates, params, checks, t));
  const [subs, setSubs] = useState<Submission[]>(() => initialSubmissions(playerEntities));
  const [tab, setTab] = useState(0);
  const [missing, setMissing] = useState<Record<number, number>>({});
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [libSave, setLibSave] = useState<LibrarySave>(() => initialSave(origin, bookMode));
  const [libError, setLibError] = useState<unknown>(null);
  // 建卡助手：打开时正在看的地方（null 是关着）；问答只留在这一页
  const [copilot, setCopilot] = useState<CopilotFocus | null>(null);
  const [turns, setTurns] = useState<CopilotTurn[]>([]);
  // 按审核意见自动改：正在改（auto 交给助手面板）、改完了几处（可以撤销回 before）
  const [auto, setAuto] = useState<{ text: string; key: number } | null>(null);
  const [fixed, setFixed] = useState<{ count: number; before: Submission[] } | null>(null);
  const beforeFix = useRef<Submission[] | null>(null);
  const [libBusy, setLibBusy] = useState(false);
  const [pdfBusy, setPdfBusy] = useState(false);
  const [libSavedAt, setLibSavedAt] = useState<string | null>(null);
  // 正在编辑的角色换了（例如刷新以后才认出来是哪个）：角色库的设置跟着换
  const originId = origin?.id;
  useEffect(() => {
    setLibSave(initialSave(origin, bookMode));
  }, [originId]); // eslint-disable-line react-hooks/exhaustive-deps
  // 自动保存：打开时先取回服务器上的草稿（没有草稿但提交过的，从上次提交的内容接着改）
  const [loaded, setLoaded] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<unknown>(null);
  const lastSaved = useRef("");
  // 这一页基于的草稿保存时间（"" 是打开时还没有草稿）：存的时候带上，草稿被别的页面改过时服务器会拒绝
  const base = useRef("");
  // 草稿在别的页面（或设备）上改过了：这一页过时了，不再自动保存，也不能提交
  const [stale, setStale] = useState(false);
  const isStale = (e: unknown) => e instanceof ApiError && e.body.code === "character.draft_stale";
  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const d = await backend.loadDraft();
        if (!alive) return;
        base.current = d.savedAt ?? "";
        if (d.sheets && d.sheets.length > 0) {
          setSubs((d.sheets as Submission[]).map(normalizeSubmission));
          lastSaved.current = JSON.stringify(d.sheets);
          setSavedAt(d.savedAt);
        } else if (bookMode) {
          // 规则书下新建：什么都没改就不暂存（免得下次打开误以为有没存的修改）
          lastSaved.current = JSON.stringify(initialSubmissions(playerEntities));
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
    const at = await backend.saveDraft(value, base.current);
    if (at) base.current = at;
    lastSaved.current = text;
    setSavedAt(at);
    setSaveError(null);
  }, [backend]);
  // 停手 2 秒后自动存
  useEffect(() => {
    if (!loaded || stale) return;
    const id = window.setTimeout(() => {
      saveNow(subs).catch((e: unknown) => (isStale(e) ? setStale(true) : setSaveError(e)));
    }, 2000);
    return () => window.clearTimeout(id);
  }, [subs, loaded, saveNow, stale]);
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
    const saved = await saveToLibrary(backend, clean, origin, libSave);
    if (saved) {
      onOrigin?.(saved);
      setLibSave((v) => ({ ...v, mode: "update", name: saved.name, password: "", newPassword: "", current: "" }));
      setLibSavedAt(new Date().toISOString());
      if (bookMode) setSavedAt(null); // 浏览器里的暂存已经存进角色库了
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
  // 导出 PDF：按页面上现在的样子（没填完的也行），文件名用角色名
  const exportPdf = async () => {
    setPdfBusy(true);
    setError(null);
    try {
      const blob = await backend.pdf({ sheets: cleanSubs() as never, lang: lang === "en" ? "en" : "zh" });
      const names = subs.map((s) => s.sheet.name.trim()).filter(Boolean);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${names.join("_") || "character"}.pdf`;
      a.click();
      window.setTimeout(() => URL.revokeObjectURL(a.href), 10_000);
    } catch (e) {
      setError(e);
    } finally {
      setPdfBusy(false);
    }
  };
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      try {
        await saveNow(subs);
      } catch (e) {
        // 这一页过时了：不能拿旧内容去提交
        if (isStale(e)) {
          setStale(true);
          return;
        }
      }
      const clean = cleanSubs();
      await call(api.POST("/api/character", { body: { sheets: clean as never } }));
      // 交给这一局以后再存进角色库；存失败（例如密码不对）不影响已经提交的
      try {
        await saveLib(clean);
      } catch (e) {
        setLibError(e);
        return;
      }
      onSubmitted?.();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  // 审核意见交给助手：打开面板、自动问，回答里的修改全部应用；改之前的卡留着，可以撤销
  useEffect(() => {
    if (!loaded || !autoFix || auto?.key === autoFix.key) return;
    beforeFix.current = subs;
    setFixed(null);
    setCopilot({ sheet: Math.min(tab, subs.length - 1) });
    setAuto({ text: t("cp.fix_review", { comments: autoFix.comments }), key: autoFix.key });
  }, [loaded, autoFix?.key]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!loaded) return <p>{t("common.loading")}</p>;
  const current = Math.min(tab, subs.length - 1);
  const tplLabel = (name: string) => templates.find((x) => x.name === name)?.label || name;
  const groupLabel = (tpl: string, g: string) => templates.find((x) => x.name === tpl)?.groups?.find((x) => x.name === g)?.label || g;
  // 助手正在看的：哪张卡，哪个分组的哪一条
  const focusSheet = copilot ? subs[Math.min(copilot.sheet, subs.length - 1)] : undefined;
  const focusEntry = copilot && focusSheet && copilot.group !== undefined && copilot.index !== undefined ? focusSheet.sheet.groups[copilot.group]?.[copilot.index] : undefined;
  const focusLabel = focusSheet
    ? [tplLabel(focusSheet.template), focusSheet.sheet.name, copilot?.group !== undefined ? groupLabel(focusSheet.template, copilot.group) : "", focusEntry?.name ?? ""].filter(Boolean).join(" / ")
    : "";
  const question = (text: string): Schemas["CopilotQuestion"] => ({
    question: text,
    history: turns.map((x) => ({ role: x.role, text: x.text })),
    sheets: subs as never,
    focus: {
      template: focusSheet?.template ?? "",
      sheet_name: focusSheet?.sheet.name ?? "",
      group: focusEntry && copilot?.group ? copilot.group : "",
      entry: (focusEntry ?? null) as never,
    },
    lang: lang === "en" ? "en" : "zh",
  });
  // 修改的标题：换掉正在编辑的那一条、换掉同名的、加一条、改字段
  const proposalTitle = (p: Schemas["CopilotProposal"]): string => {
    if (p.kind === "fields") return t("cp.prop_fields", { template: tplLabel(p.template) });
    const group = groupLabel(p.template, p.group ?? "");
    const name = entryName(p);
    if (focusEntry && copilot?.group === p.group && focusSheet?.template === p.template) return t("cp.prop_this", { name, old: focusEntry.name });
    if (p.replace) return t("cp.prop_replace", { name, group, old: p.replace });
    return t("cp.prop_entry", { name, group });
  };
  // 应用助手给的修改：条目换掉正在编辑的那一条（或同名的那一条），否则加在分组最后；字段合进卡里
  const applyProposal = (p: Schemas["CopilotProposal"]) => {
    const at = (() => {
      if (copilot && subs[copilot.sheet]?.template === p.template) return copilot.sheet;
      return subs.findIndex((x) => x.template === p.template);
    })();
    if (at < 0) return;
    setSubs((all) =>
      all.map((s, i) => {
        if (i !== at) return s;
        if (p.kind === "fields") {
          return { ...s, sheet: { ...s.sheet, name: p.name || s.sheet.name, fields: { ...s.sheet.fields, ...(p.fields as SheetDraft["fields"]) } } };
        }
        const group = p.group ?? "";
        const entry = normalizeEntry(p.entry);
        const list = [...(s.sheet.groups[group] ?? [])];
        let idx = copilot && copilot.group === group && copilot.index !== undefined && i === copilot.sheet ? copilot.index : -1;
        if (idx < 0 && p.replace) idx = list.findIndex((e) => e.name === p.replace);
        if (idx >= 0 && idx < list.length) list[idx] = entry;
        else list.push(entry);
        return { ...s, sheet: { ...s.sheet, groups: { ...s.sheet.groups, [group]: list } } };
      }),
    );
  };
  const count = (name: string) => subs.filter((s) => s.template === name).length;
  const limit = (name: string) => playerEntities.find((pe) => pe.template === name);
  const totalMissing = subs.reduce((n, _s, i) => n + (missing[i] ?? 0), 0);
  return (
    <FormBackendContext.Provider value={backend}>
    <CopilotContext.Provider value={(f) => setCopilot(f ?? { sheet: current })}>
    <div className="cf-wrap">
      {stale && (
        <div className="sk-error cf-stale" role="alert">
          {t("cf.stale")}{" "}
          <button type="button" className="sk-primary" onClick={() => window.location.reload()}>
            {t("cf.reload")}
          </button>
        </div>
      )}
      {auto && !fixed && copilot && <div className="sk-card cf-fixing">{t("cp.fixing")}</div>}
      {fixed && (
        <div className="sk-card cf-fixed" role="status">
          {t(fixed.count > 0 ? "cp.fixed" : "cp.fixed_none", { n: String(fixed.count) })}{" "}
          {fixed.count > 0 && (
            <button type="button" className="sk-link" onClick={() => {
              setSubs(fixed.before);
              setFixed(null);
            }}>
              {t("cp.undo_fix")}
            </button>
          )}
          <button type="button" className="sk-link" onClick={() => setFixed(null)}>
            {t("play.close")}
          </button>
        </div>
      )}
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
            <SheetIndexContext.Provider value={i}>
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
            </SheetIndexContext.Provider>
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
      <LibraryBox origin={origin} value={libSave} onChange={setLibSave} onSaveNow={() => void saveLibNow()} busy={libBusy} savedAt={libSavedAt} bookMode={bookMode} />
      <ErrorBox error={libError} />
      <div className="cf-footer">
        <span className="sk-hint">
          {saveError ? t("cf.save_failed") : savedAt ? t(bookMode ? "books.draft_saved" : "character.autosaved", { time: new Date(savedAt).toLocaleTimeString() }) : ""}
        </span>
        <button type="button" className="cf-pdf" title={t("cf.export_pdf_hint")} disabled={pdfBusy} onClick={() => void exportPdf()}>
          {t("cf.export_pdf")}
        </button>
        <button type="button" className="cp-button" onClick={() => setCopilot({ sheet: current })}>
          ✦ {t("cp.button")}
        </button>
        <span className={totalMissing > 0 ? "cf-footer-todo" : "cf-footer-ok"}>{totalMissing > 0 ? t("cf.missing", { n: String(totalMissing) }) : t("cf.complete")}</span>
        {stale ? null : bookMode ? (
          <button className="sk-primary" disabled={libBusy} onClick={() => void saveLibNow()}>
            {t(libSave.mode === "update" ? "lib.save_now_update" : "lib.save_now")}
          </button>
        ) : (
          <button className="sk-primary" disabled={busy} onClick={() => void submit()}>
            {t("character.submit")}
          </button>
        )}
      </div>
      <ErrorBox error={error} />
      {copilot && (
        <CopilotPanel turns={turns} setTurns={setTurns} focus={copilot} focusLabel={focusLabel} question={question} onApply={applyProposal} title={proposalTitle} onClose={() => setCopilot(null)} auto={auto} onAuto={(applied) => setFixed({ count: applied.length, before: beforeFix.current ?? subs })} />
      )}
    </div>
    </CopilotContext.Provider>
    </FormBackendContext.Provider>
  );
}
