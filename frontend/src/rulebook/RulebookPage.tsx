import { useEffect, useState } from "react";
import { api, call } from "../api/client";
import { useI18n } from "../i18n";
import { ErrorBox, LangSwitch } from "../ui/components";
import { headings, Markdown } from "../ui/markdown";

type Book = { title: string; handbook: string; scenario: string };

/** /rulebook：规则书（和剧本的公开部分）。?game=局 id 时从房间列表取（还没加入也能看），否则取自己所在的局。 */
export function RulebookPage() {
  const { t } = useI18n();
  const game = new URLSearchParams(window.location.search).get("game");
  const [book, setBook] = useState<Book | null>(null);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    const load = async (): Promise<Book> => {
      if (game) {
        const r = await call(api.GET("/api/lobby/{game_id}/rulebook", { params: { path: { game_id: game } } }));
        return { title: r.game_name, handbook: r.handbook, scenario: r.scenario };
      }
      const [r, me] = await Promise.all([call(api.GET("/api/rules")), call(api.GET("/api/me"))]);
      return { title: me.game_name, handbook: r.handbook, scenario: r.scenario };
    };
    load()
      .then((b) => {
        setBook(b);
        // 内容渲染出来以后再跳到地址里的那一节
        const hash = window.location.hash;
        if (hash) window.setTimeout(() => document.getElementById(decodeURIComponent(hash.slice(1)))?.scrollIntoView(), 50);
      })
      .catch(setError);
  }, [game]);
  if (error) {
    return (
      <main className="sk-page">
        <ErrorBox error={error} />
        <a href="/">{t("join.to_lobby")}</a>
      </main>
    );
  }
  if (!book) return <main className="sk-page">{t("common.loading")}</main>;
  const toc = headings(book.handbook).filter((h) => h.level <= 2);
  return (
    <main className="sk-page sk-rulebook">
      <header className="sk-top">
        <h1>{book.title}</h1>
        <LangSwitch />
      </header>
      <nav className="sk-toc" aria-label={t("handbook.toc")}>
        <strong>{t("handbook.toc")}</strong>
        <ul>
          {toc.map((h) => (
            <li key={h.id} className={`lv${h.level}`}>
              <a href={`#${encodeURIComponent(h.id)}`}>{h.title}</a>
            </li>
          ))}
          {book.scenario && (
            <li className="lv1">
              <a href="#scenario">{t("handbook.scenario")}</a>
            </li>
          )}
        </ul>
      </nav>
      {book.handbook ? <Markdown text={book.handbook} /> : <p className="sk-hint">{t("handbook.empty")}</p>}
      {book.scenario && (
        <section id="scenario">
          <h2>{t("handbook.scenario")}</h2>
          <Markdown text={book.scenario} />
        </section>
      )}
    </main>
  );
}
