import { useMemo, useState } from "react";
import { api, call, type Schemas } from "../api/client";
import { useI18n } from "../i18n";
import { ErrorBox, LangSwitch } from "../ui/components";
import { useAction, usePoll } from "../ui/hooks";
import { HandbookProvider, Markdown } from "../ui/markdown";
import { CharacterForm } from "../join/CharacterForm";
import { normalizeSheets, type Origin } from "../join/Library";
import { bookBackend, dropBookDraft, hasBookDraft } from "../join/formBackend";

type Char = Schemas["LibraryCharacter"];

/** 规则书这一块的页面：/books、/books/<id>、/books/<id>/scenarios/<剧本>、/books/<id>/characters/<角色 | new>。和对局列表分开。 */
export function BooksRoute() {
  const parts = window.location.pathname.split("/").filter(Boolean).map(decodeURIComponent);
  const [, book, kind, item] = parts;
  if (!book) return <BookList />;
  if (kind === "scenarios" && item) return <ScenarioPage book={book} id={item} />;
  if (kind === "characters" && item) return <CharacterPage book={book} id={item} />;
  return <BookPage id={book} />;
}

function Top({ title, back }: { title: string; back?: { href: string; label: string } }) {
  const { t } = useI18n();
  return (
    <>
      <nav className="bk-nav">
        <a href="/">{t("nav.games")}</a>
        <a href="/books" className="active">
          {t("nav.books")}
        </a>
      </nav>
      {back && (
        <p className="bk-back">
          <a href={back.href}>{back.label}</a>
        </p>
      )}
      <header className="sk-top">
        <h1>{title}</h1>
        <LangSwitch />
      </header>
    </>
  );
}

/** 所有规则书。 */
function BookList() {
  const { t } = useI18n();
  const books = usePoll(() => call(api.GET("/api/books")), 60_000);
  return (
    <main className="sk-page">
      <Top title={t("books.title")} />
      <p>{t("books.intro")}</p>
      <ErrorBox error={books.error} />
      {books.data && books.data.length === 0 && <p className="sk-hint">{t("books.empty")}</p>}
      {(books.data ?? []).map((b) => (
        <a key={b.id} className="sk-card bk-card" href={`/books/${encodeURIComponent(b.id)}`}>
          <strong>{b.name}</strong>
          {b.description && <span className="bk-desc">{b.description}</span>}
          <span className="sk-hint">
            {t("books.n_scenarios", { n: String(b.scenarios ?? 0) })} · {t("books.n_characters", { n: String(b.characters ?? 0) })}
          </span>
        </a>
      ))}
    </main>
  );
}

/** 一套规则书：规则书正文的入口、它的剧本、它的角色。 */
function BookPage({ id }: { id: string }) {
  const { t } = useI18n();
  const book = usePoll(() => call(api.GET("/api/books/{book_id}", { params: { path: { book_id: id } } })), 60_000);
  const b = book.data;
  if (!b) return <main className="sk-page">{book.error ? <ErrorBox error={book.error} /> : t("common.loading")}</main>;
  const base = `/books/${encodeURIComponent(id)}`;
  return (
    <main className="sk-page">
      <Top title={b.name} back={{ href: "/books", label: t("books.all") }} />
      {b.description && <p>{b.description}</p>}
      <p>
        <a className="sk-primary-link" href={`/rulebook?book=${encodeURIComponent(id)}`}>
          {t("books.read")}
        </a>
      </p>
      <div className="bk-columns">
        <section className="sk-card">
          <h2>{t("books.scenarios")}</h2>
          {(b.scenario_list ?? []).length === 0 && <p className="sk-hint">{t("books.no_scenarios")}</p>}
          <ul className="bk-list">
            {(b.scenario_list ?? []).map((s) => (
              <li key={s.id}>
                <a href={`${base}/scenarios/${encodeURIComponent(s.id)}`}>
                  <strong>{s.title}</strong>
                </a>
                {s.start_time && <span className="sk-hint"> {t("books.starts", { time: s.start_time.replace("T", " ") })}</span>}
                {s.intro && <p className="bk-intro">{s.intro}</p>}
              </li>
            ))}
          </ul>
        </section>
        <section className="sk-card">
          <div className="lib-head">
            <h2>{t("books.characters")}</h2>
            <a className="sk-primary-link" href={`${base}/characters/new`}>
              + {t("books.new_character")}
            </a>
          </div>
          {(b.character_list ?? []).length === 0 && <p className="sk-hint">{t("books.no_characters")}</p>}
          <ul className="bk-list">
            {(b.character_list ?? []).map((c) => (
              <CharacterRow key={c.id} book={id} c={c} onDeleted={() => void book.refresh()} />
            ))}
          </ul>
        </section>
      </div>
    </main>
  );
}

/** 角色列表的一行：打开（编辑）、删除（设了密码的要密码；页面里确认，不弹窗）。 */
function CharacterRow({ book, c, onDeleted }: { book: string; c: Char; onDeleted: () => void }) {
  const { t } = useI18n();
  const [asking, setAsking] = useState(false);
  const [password, setPassword] = useState("");
  const act = useAction();
  const remove = () =>
    void act.run(async () => {
      await call(api.POST("/api/books/{book_id}/characters/{char_id}/delete", { params: { path: { book_id: book, char_id: c.id } }, body: { password: password || null } }));
      dropBookDraft(book, c.id);
      onDeleted();
    });
  return (
    <li>
      <div className="lib-main">
        <a href={`/books/${encodeURIComponent(book)}/characters/${encodeURIComponent(c.id)}`}>
          <strong>
            {c.locked && <span title={t("lib.locked")}>🔒 </span>}
            {c.name}
          </strong>
        </a>
        {c.created_by && <span className="sk-hint"> {t("lib.by", { who: c.created_by })}</span>}
        {c.summary && <p className="lib-summary">{c.summary}</p>}
      </div>
      {asking ? (
        <div className="bk-confirm">
          <span>{t("books.delete_confirm", { name: c.name })}</span>
          {c.locked && <input type="password" value={password} placeholder={t("lib.password")} onChange={(e) => setPassword(e.target.value)} />}
          <button type="button" className="wb-danger" disabled={act.busy} onClick={remove}>
            {t("books.delete")}
          </button>
          <button type="button" className="sk-link" onClick={() => setAsking(false)}>
            {t("common.cancel")}
          </button>
          <ErrorBox error={act.error} />
        </div>
      ) : (
        <button type="button" className="sk-link wb-danger" onClick={() => setAsking(true)}>
          {t("books.delete")}
        </button>
      )}
    </li>
  );
}

/** 剧本的公开部分。 */
function ScenarioPage({ book, id }: { book: string; id: string }) {
  const { t } = useI18n();
  const s = usePoll(() => call(api.GET("/api/books/{book_id}/scenarios/{scenario_id}", { params: { path: { book_id: book, scenario_id: id } } })), 600_000);
  if (!s.data) return <main className="sk-page">{s.error ? <ErrorBox error={s.error} /> : t("common.loading")}</main>;
  return (
    <main className="sk-page sk-rulebook">
      <Top title={s.data.title} back={{ href: `/books/${encodeURIComponent(book)}`, label: `← ${s.data.book}` }} />
      <Markdown text={s.data.text} />
    </main>
  );
}

/** 不进局编辑角色库里的角色（id 是 new 时新建）：设了密码的先要密码；改的东西先暂存在浏览器里，点“存进角色库”才保存。 */
function CharacterPage({ book, id }: { book: string; id: string }) {
  const { t } = useI18n();
  const form = usePoll(() => call(api.GET("/api/books/{book_id}/form", { params: { path: { book_id: book } } })), 600_000);
  const detail = usePoll(() => call(api.GET("/api/books/{book_id}", { params: { path: { book_id: book } } })), 600_000);
  const [opened, setOpened] = useState<{ sheets: unknown[] | null; origin: Origin | null } | null>(id === "new" ? { sheets: null, origin: null } : null);
  const [password, setPassword] = useState("");
  const [current, setCurrent] = useState(id); // 新建的存进去以后，接着编辑的就是它
  const [formKey, setFormKey] = useState(0);
  // 打开时浏览器里有没存进角色库的修改：提示一下，可以放弃
  const [local, setLocal] = useState(() => id === "new" && hasBookDraft(book, "new"));
  const act = useAction();
  const summary = (detail.data?.character_list ?? []).find((c) => c.id === id);
  const entities = useMemo(() => (form.data?.player_entities ?? []) as unknown as { template: string; min: number; max: number }[], [form.data]);
  const open = (pw: string | null) =>
    void act.run(async () => {
      const full = await call(api.POST("/api/books/{book_id}/characters/{char_id}/open", { params: { path: { book_id: book, char_id: id } }, body: { password: pw } }));
      setLocal(hasBookDraft(book, id));
      setOpened({
        sheets: normalizeSheets(full.sheets, entities),
        origin: { id: full.id, name: full.name, summary: full.summary ?? "", password: pw, locked: full.locked ?? false, own: true },
      });
    });
  const backend = useMemo(() => bookBackend(book, current, opened?.sheets ?? null), [book, current, opened]);
  const back = { href: `/books/${encodeURIComponent(book)}`, label: `← ${detail.data?.name ?? ""}` };
  if (!form.data || !detail.data) return <main className="sk-page">{form.error || detail.error ? <ErrorBox error={form.error ?? detail.error} /> : t("common.loading")}</main>;
  if (id !== "new" && !summary && !opened) {
    return (
      <main className="sk-page">
        <Top title={t("books.characters")} back={back} />
        <p className="sk-error">{t("codes.library.not_found")}</p>
      </main>
    );
  }
  if (!opened) {
    return (
      <main className="sk-page">
        <Top title={summary?.name ?? ""} back={back} />
        {summary?.locked ? (
          <div className="sk-card">
            <p>{t("books.need_password")}</p>
            <div className="lib-pw">
              <input type="password" autoFocus value={password} placeholder={t("lib.password")} onChange={(e) => setPassword(e.target.value)} onKeyDown={(e) => e.key === "Enter" && open(password)} />
              <button type="button" className="sk-primary" disabled={act.busy} onClick={() => open(password)}>
                {t("books.unlock")}
              </button>
            </div>
          </div>
        ) : (
          <p>
            <button type="button" className="sk-primary" disabled={act.busy} onClick={() => open(null)}>
              {t("books.unlock")}
            </button>
          </p>
        )}
        <ErrorBox error={act.error} />
      </main>
    );
  }
  return (
    <main className="sk-page sk-join">
      <Top title={opened.origin ? opened.origin.name : t("books.new_character")} back={back} />
      {local && (
        <p className="sk-card bk-local">
          {t("books.local_draft")}{" "}
          <button
            type="button"
            className="sk-link"
            onClick={() => {
              dropBookDraft(book, current);
              setLocal(false);
              setFormKey((k) => k + 1);
            }}
          >
            {t(opened.origin ? "books.drop_draft" : "books.drop_new")}
          </button>
        </p>
      )}
      <HandbookProvider text={form.data.handbook} href={`/rulebook?book=${encodeURIComponent(book)}`}>
        <CharacterForm
          key={formKey}
          templates={form.data.templates as unknown as Schemas["EntityTemplate"][]}
          playerEntities={entities}
          params={form.data.params}
          checks={form.data.checks}
          origin={opened.origin}
          backend={backend}
          bookMode
          onOrigin={(o) => {
            // 存进角色库了：浏览器里的暂存不用留；新建的从此按它的 id 编辑
            dropBookDraft(book, current);
            setLocal(false);
            if (current !== o.id) {
              window.history.replaceState(null, "", `/books/${encodeURIComponent(book)}/characters/${encodeURIComponent(o.id)}`);
              setCurrent(o.id);
            }
            setOpened((x) => (x ? { ...x, origin: o } : x));
          }}
        />
      </HandbookProvider>
    </main>
  );
}
