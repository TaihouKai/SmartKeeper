import { useEffect, useState } from "react";
import { api, call } from "../api/client";
import { useI18n } from "../i18n";
import { ErrorBox, LangSwitch } from "../ui/components";
import { headings, Markdown } from "../ui/markdown";

type Book = { title: string; text: string };

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
  useEffect(() => {
    const load = async (): Promise<Book> => {
      if (bookId) {
        const b = await call(api.GET("/api/books/{book_id}", { params: { path: { book_id: bookId } } }));
        return { title: b.name, text: part === "handbook" ? (b.handbook ?? "") : "" };
      }
      if (game) {
        const r = await call(api.GET("/api/lobby/{game_id}/rulebook", { params: { path: { game_id: game } } }));
        return { title: r.game_name, text: r[part] };
      }
      const [r, me] = await Promise.all([call(api.GET("/api/rules")), call(api.GET("/api/me"))]);
      return { title: me.game_name, text: r[part] };
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
        <LangSwitch />
      </header>
      {toc.length > 1 && (
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
      {book.text ? <Markdown text={book.text} /> : <p className="sk-hint">{t(empty)}</p>}
    </main>
  );
}
