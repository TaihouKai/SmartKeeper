import { useMemo, useState } from "react";
import type { Schemas } from "../api/client";
import { useI18n } from "../i18n";

type Entry = Schemas["LoreOut"];

const SHOWN = 80; // 索引一次最多列这么多条

/** 资料库：按标题、关键词和正文搜，左边是索引（标题），点了在右边看正文。 */
export function LoreBrowser({ entries }: { entries: Entry[] }) {
  const { t } = useI18n();
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const found = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return entries;
    // 标题、关键词命中的排在正文命中的前面
    const head = entries.filter((e) => e.title.toLowerCase().includes(s) || e.keys.some((k) => k.toLowerCase().includes(s)));
    const body = entries.filter((e) => !head.includes(e) && e.content.toLowerCase().includes(s));
    return [...head, ...body];
  }, [entries, q]);
  const current = entries.find((e) => e.title === open) ?? null;
  return (
    <section className="sk-lore">
      <p className="sk-hint">{t("lore.hint", { n: String(entries.length) })}</p>
      <input className="sk-lore-search" value={q} placeholder={t("lore.search")} onChange={(e) => setQ(e.target.value)} autoFocus />
      <div className="sk-lore-body">
        <nav className="sk-lore-index" aria-label={t("lore.index")}>
          {found.slice(0, SHOWN).map((e) => (
            <button key={e.title} type="button" className={e.title === open ? "sk-link active" : "sk-link"} onClick={() => setOpen(e.title)}>
              {e.title}
            </button>
          ))}
          {found.length > SHOWN && <p className="sk-hint">{t("lore.more", { n: String(found.length - SHOWN) })}</p>}
          {found.length === 0 && <p className="sk-hint">{t("lore.none")}</p>}
        </nav>
        <article className="sk-lore-entry">
          {current ? (
            <>
              <h2>{current.title}</h2>
              <p className="sk-hint">{current.keys.join("、")}</p>
              {current.content.split("\n").map((line, i) => (line.trim() ? <p key={i}>{line}</p> : null))}
            </>
          ) : (
            <p className="sk-hint">{t("lore.pick")}</p>
          )}
        </article>
      </div>
    </section>
  );
}
