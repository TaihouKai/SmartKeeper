import { useEffect, useState } from "react";
import { api, call, type Schemas } from "../api/client";
import { useI18n } from "../i18n";
import { ErrorBox, LangSwitch } from "../ui/components";
import { headings, Markdown } from "../ui/markdown";
import { LoreBrowser } from "./LoreBrowser";

/** lore：资料库有几条（有的话页面上有按钮能查），以及怎么取。 */
type Book = { title: string; text: string; lore: number; loadLore: () => Promise<Schemas["LoreOut"][]> };

/**
 * /rulebook：规则书；/scenario：剧本的公开部分。两者分开（一套规则书下面有很多剧本）。
 * ?game=局 id 时从房间列表取（还没加入也能看），否则取自己所在的局。
 */
export function RulebookPage({ part }: { part: "handbook" | "scenario" }) {
  const { t } = useI18n();
  const query = new URLSearchParams(window.location.search);
  const game = query.get("game");
  const bookId = query.get("book"); // 规则书总览里打开的：不经过哪一局
  const [book, setBook] = useState<Book | null>(null);
  const [error, setError] = useState<unknown>(null);
  // 资料库：点了按钮才去取（几百条，平时不用下载）
  const [lore, setLore] = useState<Schemas["LoreOut"][] | null>(null);
  const [showLore, setShowLore] = useState(false);
  const openLore = () => {
    setShowLore(true);
    if (lore === null && book) book.loadLore().then(setLore).catch(setError);
  };
  useEffect(() => {
    const load = async (): Promise<Book> => {
      const mine = () => call(api.GET("/api/rules/lore"));
      if (bookId) {
        const b = await call(api.GET("/api/books/{book_id}", { params: { path: { book_id: bookId } } }));
        return {
          title: b.name,
          text: part === "handbook" ? (b.handbook ?? "") : "",
          lore: b.lore_count ?? 0,
          loadLore: () => call(api.GET("/api/books/{book_id}/lore", { params: { path: { book_id: bookId } } })),
        };
      }
      if (game) {
        // 自己在这一局里：按座位取（不在房间列表里的局也行）；没加入的从房间列表取
        try {
          const [r, me] = await Promise.all([call(api.GET("/api/rules")), call(api.GET("/api/me"))]);
          return { title: me.game_name, text: r[part], lore: r.lore_count ?? 0, loadLore: mine };
        } catch {
          const r = await call(api.GET("/api/lobby/{game_id}/rulebook", { params: { path: { game_id: game } } }));
          return {
            title: r.game_name,
            text: r[part],
            lore: r.lore_count ?? 0,
            loadLore: () => call(api.GET("/api/lobby/{game_id}/lore", { params: { path: { game_id: game } } })),
          };
        }
      }
      const [r, me] = await Promise.all([call(api.GET("/api/rules")), call(api.GET("/api/me"))]);
      return { title: me.game_name, text: r[part], lore: r.lore_count ?? 0, loadLore: mine };
    };
    load()
      .then((b) => {
        setBook(b);
        // 内容渲染出来以后再跳到地址里的那一节
        const hash = window.location.hash;
        if (hash) window.setTimeout(() => document.getElementById(decodeURIComponent(hash.slice(1)))?.scrollIntoView(), 50);
      })
      .catch(setError);
  }, [game, bookId, part]);
  if (error) {
    return (
      <main className="sk-page">
        <ErrorBox error={error} />
        <a href="/">{t("join.to_lobby")}</a>
      </main>
    );
  }
  if (!book) return <main className="sk-page">{t("common.loading")}</main>;
  const toc = headings(book.text).filter((h) => h.level <= 2);
  const empty = part === "handbook" ? "handbook.empty" : "handbook.no_scenario";
  return (
    <main className="sk-page sk-rulebook">
      <header className="sk-top">
        <h1>
          {book.title} · {t(part === "handbook" ? "handbook.title" : "handbook.scenario")}
        </h1>
        {part === "handbook" && book.lore > 0 && (
          <button type="button" onClick={() => (showLore ? setShowLore(false) : openLore())}>
            {showLore ? t("lore.back") : t("lore.open", { n: String(book.lore) })}
          </button>
        )}
        <LangSwitch />
      </header>
      {showLore && (lore ? <LoreBrowser entries={lore} /> : <p>{t("common.loading")}</p>)}
      {!showLore && toc.length > 1 && (
        <nav className="sk-toc" aria-label={t("handbook.toc")}>
          <strong>{t("handbook.toc")}</strong>
          <ul>
            {toc.map((h) => (
              <li key={h.id} className={`lv${h.level}`}>
                <a href={`#${encodeURIComponent(h.id)}`}>{h.title}</a>
              </li>
            ))}
          </ul>
        </nav>
      )}
      {!showLore && (book.text ? <Markdown text={book.text} /> : <p className="sk-hint">{t(empty)}</p>)}
    </main>
  );
}
