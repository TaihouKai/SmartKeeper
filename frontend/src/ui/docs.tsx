import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, call, type Schemas } from "../api/client";
import { useI18n } from "../i18n";

export type DocEntry = Schemas["DocEntry"];
export type DocCategory = DocEntry["category"] | "pack";
/** 规则包里的名字（字段、推导值、检定、参数、表……）：说明是现成的文字，不是翻译键。 */
export type PackName = { name: string; sig: string; text: string; kind: string };

const CATEGORIES: DocCategory[] = ["basics", "config", "shape", "verb", "script", "function", "variable", "check", "pack"];

// 目录只取一次（后端从公式语言的定义生成），编辑器的悬停提示也用它
let catalog: DocEntry[] = [];
const listeners = new Set<() => void>();
let loading: Promise<void> | null = null;

export function docsCatalog(): readonly DocEntry[] {
  return catalog;
}

/** 测试和预加载用：直接设目录。 */
export function setDocsCatalog(entries: DocEntry[]): void {
  catalog = entries;
  listeners.forEach((f) => f());
}

export function loadDocs(): Promise<void> {
  loading ??= call(api.GET("/api/lobby/docs"))
    .then((x) => setDocsCatalog(x))
    .catch(() => {
      loading = null;
    });
  return loading;
}

function useCatalog(): readonly DocEntry[] {
  const [, tick] = useState(0);
  useEffect(() => {
    const f = () => tick((n) => n + 1);
    listeners.add(f);
    void loadDocs();
    return () => {
      listeners.delete(f);
    };
  }, []);
  return catalog;
}

type Ctx = {
  /** 打开手册；给了 query 就先搜它，给了 category 就先翻到那一类 */
  open: (opts?: { query?: string; category?: DocCategory }) => void;
  /** 当前页面的规则包名字（建卡页、规则编辑器各自设） */
  setPackNames: (names: PackName[]) => void;
  /** 手册现在开着没有 */
  shown: boolean;
};

const DocsContext = createContext<Ctx | null>(null);

export function useDocs(): Ctx | null {
  return useContext(DocsContext);
}

/** 把当前规则包的名字交给手册（离开页面时清掉）。 */
export function useDocsPackNames(names: PackName[]): void {
  const ctx = useDocs();
  const key = JSON.stringify(names);
  useEffect(() => {
    ctx?.setPackNames(names);
    return () => ctx?.setPackNames([]);
  }, [key]);
}

export function DocsProvider({ children }: { children: ReactNode }) {
  const [shown, setShown] = useState<{ query: string; category: DocCategory | "all" } | null>(null);
  const [pack, setPack] = useState<PackName[]>([]);
  const ctx = useMemo<Ctx>(
    () => ({
      open: (o) => setShown({ query: o?.query ?? "", category: o?.category ?? "all" }),
      setPackNames: setPack,
      shown: shown !== null,
    }),
    [shown],
  );
  return (
    <DocsContext.Provider value={ctx}>
      {children}
      {shown && <DocsPanel initial={shown} pack={pack} onClose={() => setShown(null)} />}
    </DocsContext.Provider>
  );
}

/** 页面左边缘固定的“语法手册”标签：滚到哪里都看得见，手册开着时不显示。 */
export function DocsTab() {
  const { t } = useI18n();
  const docs = useDocs();
  if (!docs || docs.shown) return null;
  return (
    <button type="button" className="sk-docs-tab" onClick={() => docs.open()}>
      {t("docs.title")}
    </button>
  );
}

/** 一行小字 + “语法手册”按钮，代替编辑框底下的长提示。 */
export function DocsLink({ text, category, query }: { text?: string; category?: DocCategory; query?: string }) {
  const { t } = useI18n();
  const docs = useDocs();
  return (
    <p className="sk-hint sk-docs-link">
      {text}{" "}
      {docs && (
        <button type="button" className="sk-link" onClick={() => docs.open({ category, query })}>
          {t("docs.open")}
        </button>
      )}
    </p>
  );
}

/** 不区分大小写的包含。 */
function has(hay: string, q: string): boolean {
  return hay.toLowerCase().includes(q);
}

function DocsPanel({ initial, pack, onClose }: { initial: { query: string; category: DocCategory | "all" }; pack: PackName[]; onClose: () => void }) {
  const { t } = useI18n();
  return (
    <aside className="sk-drawer sk-docs-drawer" aria-label={t("docs.title")}>
      <div className="sk-drawer-head">
        <h3>{t("docs.title")}</h3>
        <button type="button" className="sk-link" onClick={onClose}>
          {t("play.close")}
        </button>
      </div>
      <DocsBody initial={initial} pack={pack} />
    </aside>
  );
}

/** 手册的内容：搜索框、分类索引、按类列出的写法。 */
export function DocsBody({ initial = { query: "", category: "all" }, pack = [] }: { initial?: { query: string; category: DocCategory | "all" }; pack?: PackName[] }) {
  const { t } = useI18n();
  const entries = useCatalog();
  const [query, setQuery] = useState(initial.query);
  const [cat, setCat] = useState<DocCategory | "all">(initial.category);
  const box = useRef<HTMLInputElement>(null);
  useEffect(() => box.current?.focus(), []);
  useEffect(() => {
    setQuery(initial.query);
    setCat(initial.category);
  }, [initial]);
  const q = query.trim().toLowerCase();
  // 搜名字、写法、说明（翻译后的文字）和参数
  const builtins = entries.filter(
    (d) => !q || has(d.name, q) || has(d.sig, q) || has(t(d.desc), q) || (d.params ?? []).some(([p, k]) => has(p, q) || has(t(k), q)),
  );
  const own = pack.filter((p) => !q || has(p.name, q) || has(p.sig, q) || has(p.text, q) || has(p.kind, q));
  const groups = CATEGORIES.map((c) => ({
    c,
    rows: c === "pack" ? [] : builtins.filter((d) => d.category === c),
    own: c === "pack" ? own : [],
  })).filter((g) => (cat === "all" || g.c === cat) && g.rows.length + g.own.length > 0);
  const count = (c: DocCategory) => (c === "pack" ? own.length : builtins.filter((d) => d.category === c).length);
  return (
    <div className="sk-docs">
      <input ref={box} type="search" className="sk-docs-search" value={query} placeholder={t("docs.search")} onChange={(e) => { setQuery(e.target.value); if (e.target.value.trim()) setCat("all"); }} />
      <p className="sk-hint">{t("docs.prefix_rule")}</p>
      <nav className="sk-docs-cats">
        <button type="button" className={cat === "all" ? "on" : ""} onClick={() => setCat("all")}>
          {t("docs.cat.all")}
        </button>
        {CATEGORIES.filter((c) => c !== "pack" || pack.length > 0).map((c) => (
          <button key={c} type="button" className={cat === c ? "on" : ""} disabled={count(c) === 0} onClick={() => setCat(c)}>
            {t(`docs.cat.${c}`)} <span className="sk-hint">{count(c)}</span>
          </button>
        ))}
      </nav>
      {groups.length === 0 && <p className="sk-hint">{t("docs.none")}</p>}
      {groups.map((g) => (
        <section key={g.c} className="sk-docs-group">
          <h4>{t(`docs.cat.${g.c}`)}</h4>
          {g.c === "verb" && <p className="sk-hint">{t("docs.verb_note")}</p>}
          <dl>
            {g.rows.map((d) => (
              <div key={`${d.category}:${d.name}`} className="sk-docs-item">
                <dt>
                  <code>{d.category === "verb" ? `target.${d.sig}` : d.sig}</code>
                </dt>
                <dd>
                  {t(d.desc)}
                  {(d.params ?? []).length > 0 && (
                    <ul>
                      {(d.params ?? []).map(([p, k]) => (
                        <li key={p}>
                          <code>{p}</code>：{t(k)}
                        </li>
                      ))}
                    </ul>
                  )}
                </dd>
              </div>
            ))}
            {g.own.map((p) => (
              <div key={`${p.kind}:${p.name}`} className="sk-docs-item">
                <dt>
                  <code>{p.sig}</code> <span className="cf-tag">{p.kind}</span>
                </dt>
                <dd>{p.text}</dd>
              </div>
            ))}
          </dl>
        </section>
      ))}
    </div>
  );
}
