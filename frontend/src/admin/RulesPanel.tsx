import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { api, call, type Schemas } from "../api/client";
import { useI18n } from "../i18n";
import { ErrorBox, Mover } from "../ui/components";
import { translateCode } from "../ui/errors";
import { useAction, usePoll } from "../ui/hooks";
import type { Validate } from "./fieldCard";
import { WorkbenchProvider } from "./rules/ctx";
import { Ide } from "./rules/ide/Ide";
import { blankGroup, blankPack, blankTemplate, describePath, docFor, getAt, openPath, renameTemplate, selForPath, selKey, setAt, withEngineDefaults, type Pack, type Sel } from "./rules/model";
import { fillCheck, fillConfig } from "../ui/skillConfig";
import { Outline } from "./rules/Outline";
import { ChecksSection, DerivedSection, FieldsSection, FormulasSection, GroupSection, HandbookSection, InsightsSection, PlayersSection, SamplesSection, TablesSection, TextSection, WorldSection } from "./rules/sections";
import "./rules/workbench.css";


function when(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleString() : "";
}

function stored(key: string, fallback: number): number {
  try {
    const v = Number(window.localStorage.getItem(key));
    return Number.isFinite(v) && v > 0 ? v : fallback;
  } catch {
    return fallback;
  }
}

/** 点一下展开、点外面收起的小浮层。 */
function Popover({ label, className, children, open, setOpen }: { label: ReactNode; className?: string; children: ReactNode; open: boolean; setOpen: (o: boolean) => void }) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [open, setOpen]);
  return (
    <div className="wb-pop-wrap" ref={box}>
      <button type="button" className={className} aria-expanded={open} onClick={() => setOpen(!open)}>
        {label}
      </button>
      {open && <div className="wb-pop">{children}</div>}
    </div>
  );
}

/**
 * “规则”面板：全屏的规则编辑工作台。
 * 顶栏是规则包和保存；左边是目录，中间是选中的那一节，右边是写公式和技能脚本的 IDE。
 */
export function RulesPanel() {
  const { t, lang } = useI18n();
  const packs = usePoll(() => call(api.GET("/api/admin/rulepacks")), 600_000);
  const [current, setCurrent] = useState<{ id: string | null; version: number | null }>({ id: null, version: null });
  const [pack, setPack] = useState<Pack>(() => blankPack(t));
  const [problems, setProblems] = useState<Schemas["Problem"][] | null>(null);
  const [checkError, setCheckError] = useState<unknown>(null);
  const [draftAt, setDraftAt] = useState<string | null>(null);
  const [draftError, setDraftError] = useState<unknown>(null);
  const [choice, setChoice] = useState("");
  const [sel, setSel] = useState<Sel>({ k: "world" });
  const [docs, setDocs] = useState<string[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [ideOpen, setIdeOpen] = useState(true);
  const [ideWidth, setIdeWidth] = useState(() => stored("sk.rules.ide", 560));
  const [navOpen, setNavOpen] = useState(false);
  const [packMenu, setPackMenu] = useState(false);
  const [problemList, setProblemList] = useState(false);
  const act = useAction();
  // 上次打开或保存时的内容；和它不同就是“有未保存的修改”
  const baseline = useRef(JSON.stringify(pack));
  const idRef = useRef<string | null>(null);
  const creating = useRef<Promise<string> | null>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  idRef.current = current.id;
  const dirty = JSON.stringify(pack) !== baseline.current;

  const load = (p: Pack, id: string | null, version: number | null, draft: string | null) => {
    // 基准是原样的内容：补了引擎新增的必需项就算有修改，几秒后自动存成草稿
    baseline.current = JSON.stringify(p);
    setPack(withEngineDefaults(p, t));
    setCurrent({ id, version });
    setDraftAt(draft);
    setChoice(id ? `${id}|${version ?? "draft"}` : "");
    setDocs([]);
    setActive(null);
    setSel({ k: "world" });
    setPackMenu(false);
  };

  const validate: Validate = useCallback(
    (formula, template, inEntry, scope, other) => call(api.POST("/api/admin/rulepacks/formula", { body: { pack, formula, template, in_entry: inEntry ?? null, scope: scope ?? null, other: other ?? "" } })),
    [pack],
  );
  useEffect(() => {
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

  // ---------------- 目录和 IDE ----------------
  const select = (s: Sel) => {
    setSel(s);
    setNavOpen(false);
    contentRef.current?.scrollTo({ top: 0 });
  };
  const openDoc = useCallback(
    (raw: string) => {
      const path = openPath(raw);
      // 条目的技能设置：这个分组用得上的项预先填好（已有的不动）
      setPack((p) => {
        const d = docFor(p, path);
        if (d?.kind === "check") {
          // 检定的代码：没写的项预先填好
          const cur = String(getAt(p, path) ?? "");
          const next = fillCheck(cur, t);
          return next === cur ? p : setAt(p, path, next);
        }
        if (d?.kind !== "entry" || !d.entry) return p;
        const cur = String(getAt(p, `${path}.config`) ?? "");
        const next = fillConfig(cur, p.templates[d.entry.t]?.groups?.[d.entry.g] ?? {}, t);
        return next === cur ? p : setAt(p, `${path}.config`, next);
      });
      setDocs((d) => (d.includes(path) ? d : [...d, path]));
      setActive(path);
      setIdeOpen(true);
    },
    [t],
  );
  const closeDoc = (path: string) => {
    const i = docs.indexOf(path);
    const next = docs.filter((p) => p !== path);
    setDocs(next);
    if (active === path) setActive(next[Math.min(i, next.length - 1)] ?? null);
  };
  const reveal = (path: string) => select(selForPath(path));
  // 删了行或改了结构，打不开的文档自动关掉
  const liveDocs = docs.filter((p) => docFor(pack, p));
  const liveActive = active && liveDocs.includes(active) ? active : (liveDocs[liveDocs.length - 1] ?? null);

  const dragIde = (e: React.PointerEvent) => {
    e.preventDefault();
    const startX = e.clientX;
    const startW = ideWidth;
    let w = startW;
    const move = (ev: PointerEvent) => {
      w = Math.min(Math.max(320, startW + startX - ev.clientX), window.innerWidth - 480);
      setIdeWidth(w);
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      try {
        window.localStorage.setItem("sk.rules.ide", String(Math.round(w)));
      } catch {
        /* 存不了就算了 */
      }
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  // 下拉菜单里选中的一项：规则包 id 加版本号（草稿是 null）
  const [pid = "", ver = ""] = choice.split("|");
  const picked = choice ? { id: pid, version: ver === "draft" ? null : Number(ver) } : null;
  let editing = t("rules.editing_new");
  if (current.id && current.version !== null) editing = t("rules.wb.version", { v: String(current.version) });
  else if (current.id) editing = t("rules.wb.draft");

  const setTemplate = (i: number, x: Pack["templates"][number]) => setPack((p) => renameTemplate(p, i, x));
  const content = (() => {
    const s = sel;
    if (s.k === "fields" || s.k === "derived" || s.k === "group") {
      const tpl = pack.templates[s.t];
      if (!tpl) return <p className="sk-hint">{t("rules.wb.gone")}</p>;
      const base = `templates[${s.t}]`;
      if (s.k === "fields")
        return (
          <FieldsSection
            tpl={tpl}
            base={base}
            validate={validate}
            onChange={(x) => setTemplate(s.t, x)}
            onRemove={() => {
              setPack((p) => ({ ...p, templates: p.templates.filter((_, j) => j !== s.t) }));
              select({ k: "world" });
            }}
            mover={<Mover index={s.t} count={pack.templates.length} onMove={(from, to) => { setPack((p) => ({ ...p, templates: movedList(p.templates, from, to) })); setSel({ k: "fields", t: to }); }} />}
          />
        );
      if (s.k === "derived") return <DerivedSection tpl={tpl} validate={validate} base={base} onChange={(x) => setTemplate(s.t, x)} />;
      const groups = tpl.groups ?? [];
      const g = groups[s.g];
      if (!g) return <p className="sk-hint">{t("rules.wb.gone")}</p>;
      return (
        <GroupSection
          key={`${s.t}:${s.g}`}
          tpl={tpl}
          g={g}
          base={`${base}.groups[${s.g}]`}
          checks={(pack.checks ?? []).map((c) => c.name).filter(Boolean)}
          validate={validate}
          onChange={(x) => setTemplate(s.t, { ...tpl, groups: groups.map((y, j) => (j === s.g ? x : y)) })}
          onRemove={() => {
            setTemplate(s.t, { ...tpl, groups: groups.filter((_, j) => j !== s.g) });
            select({ k: "fields", t: s.t });
          }}
          mover={<Mover index={s.g} count={groups.length} onMove={(from, to) => { setTemplate(s.t, { ...tpl, groups: movedList(groups, from, to) }); setSel({ k: "group", t: s.t, g: to }); }} />}
        />
      );
    }
    if (s.k === "world") return <WorldSection pack={pack} onChange={setPack} />;
    if (s.k === "players") return <PlayersSection pack={pack} onChange={setPack} />;
    if (s.k === "formulas") return <FormulasSection pack={pack} onChange={setPack} validate={validate} />;
    if (s.k === "tables") return <TablesSection pack={pack} onChange={setPack} />;
    if (s.k === "checks") return <ChecksSection pack={pack} onChange={setPack} />;
    if (s.k === "text") return <TextSection pack={pack} onChange={setPack} />;
    if (s.k === "handbook") return <HandbookSection pack={pack} onChange={setPack} />;
    if (s.k === "insights") return <InsightsSection pack={pack} onChange={setPack} validate={validate} />;
    return <SamplesSection pack={pack} onChange={setPack} />;
  })();

  const nProblems = problems?.length ?? 0;
  return (
    <WorkbenchProvider value={{ open: openDoc, active: liveActive, problems: problems ?? [] }}>
      <div className={`wb${ideOpen ? " wb-ide-on" : ""}${navOpen ? " wb-nav-on" : ""}`} style={{ "--wb-ide-w": `${ideWidth}px` } as React.CSSProperties}>
        <div className="wb-bar">
          <button type="button" className="wb-icon wb-nav-toggle" aria-label={t("rules.outline")} onClick={() => setNavOpen(!navOpen)}>
            ☰
          </button>
          <Popover
            open={packMenu}
            setOpen={setPackMenu}
            className="wb-pack"
            label={
              <>
                <span className="wb-pack-name">{pack.world.name || t("rules.wb.untitled")}</span>
                <span className="wb-pack-state">{editing}</span>
                <span className="wb-caret">▾</span>
              </>
            }
          >
            <h4>{t("rules.packs")}</h4>
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
            <div className="sk-row">
              <button className="sk-primary" disabled={!picked} onClick={() => picked && (picked.version === null ? openDraft(picked.id) : open(picked.id, picked.version))}>
                {t("rules.open")}
              </button>
              {picked && picked.version !== null && (
                <a className="sk-button" href={`/api/admin/rulepacks/${picked.id}/versions/${picked.version}/export`}>
                  {t("rules.export")}
                </a>
              )}
              {picked && (
                <button onClick={() => (picked.version === null ? discardDraft(picked.id) : remove(picked.id, picked.version))}>{picked.version === null ? t("rules.draft_discard") : t("common.remove")}</button>
              )}
            </div>
            <hr />
            <div className="sk-row">
              <button onClick={() => load(blankPack(t), null, null, null)}>{t("rules.new")}</button>
              <label className="sk-button sk-file">
                {t("rules.import")}
                <input type="file" accept=".json,application/json" onChange={(e) => e.target.files?.[0] && importFile(e.target.files[0])} />
              </label>
            </div>
          </Popover>
          <div className="wb-bar-spacer" />
          <Popover
            open={problemList}
            setOpen={setProblemList}
            className={problems === null ? "wb-chip" : nProblems ? "wb-chip bad" : "wb-chip ok"}
            label={problems === null ? t("rules.checking") : nProblems ? t("rules.wb.problems", { n: String(nProblems) }) : t("rules.wb.no_problems")}
          >
            {nProblems === 0 ? (
              <p className="sk-hint">{t("rules.valid")}</p>
            ) : (
              <ul className="wb-problem-list">
                {(problems ?? []).slice(0, 100).map((p, i) => {
                  const where = describePath(t, pack, p.path ?? "").join(" › ");
                  return (
                    <li key={i}>
                      <button
                        type="button"
                        onClick={() => {
                          if (p.path) {
                            reveal(p.path);
                            if (docFor(pack, p.path)) openDoc(p.path);
                          }
                          setProblemList(false);
                        }}
                      >
                        {where && <span className="wb-problem-where">{where}</span>}
                        <span>{translateCode(lang, p.code, p.params)}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </Popover>
          <span className="wb-saved">{dirty ? t("rules.unsaved") : draftAt ? t("rules.wb.saved_at", { time: new Date(draftAt).toLocaleTimeString() }) : ""}</span>
          <button disabled={act.busy} onClick={() => void act.run(() => saveDraft(pack))}>
            {t("rules.save_draft")}
          </button>
          <button className="sk-primary" disabled={act.busy || problems === null || nProblems > 0} title={nProblems ? t("rules.wb.fix_first") : undefined} onClick={save}>
            {t("rules.save_version")}
          </button>
          <button type="button" className={ideOpen ? "wb-icon active" : "wb-icon"} title={t("ide.toggle")} aria-pressed={ideOpen} onClick={() => setIdeOpen(!ideOpen)}>
            {"</>"}
          </button>
        </div>
        <ErrorBox error={act.error ?? draftError ?? checkError} />
        <div className="wb-body">
          <Outline
            pack={pack}
            current={sel}
            onSelect={select}
            problems={problems ?? []}
            onAddTemplate={() => {
              setPack((p) => ({ ...p, templates: [...p.templates, blankTemplate(`template_${p.templates.length + 1}`, t)] }));
              select({ k: "fields", t: pack.templates.length });
            }}
            onAddGroup={(ti) => {
              const tpl = pack.templates[ti];
              if (!tpl) return;
              setTemplate(ti, { ...tpl, groups: [...(tpl.groups ?? []), blankGroup()] });
              select({ k: "group", t: ti, g: (tpl.groups ?? []).length });
            }}
          />
          <div className="wb-scrim" onClick={() => setNavOpen(false)} />
          <main className="wb-content" ref={contentRef} key={selKey(sel)}>
            <div className="wb-content-inner">{content}</div>
          </main>
          {ideOpen && <div className="wb-resize" role="separator" aria-orientation="vertical" onPointerDown={dragIde} />}
          {ideOpen && (
            <aside className="wb-ide-pane">
              <Ide
                pack={pack}
                setPack={setPack}
                validate={validate}
                docs={liveDocs}
                active={liveActive}
                onActivate={setActive}
                onClose={closeDoc}
                onOpen={openDoc}
                onReveal={reveal}
                onGoSamples={() => select({ k: "samples" })}
              />
              <button type="button" className="wb-ide-close" aria-label={t("ide.toggle")} onClick={() => setIdeOpen(false)}>
                ×
              </button>
            </aside>
          )}
        </div>
      </div>
    </WorkbenchProvider>
  );
}

function movedList<X>(list: X[], from: number, to: number): X[] {
  if (to < 0 || to >= list.length) return list;
  const out = [...list];
  const [x] = out.splice(from, 1);
  out.splice(to, 0, x as X);
  return out;
}
