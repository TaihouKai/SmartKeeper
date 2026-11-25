import DOMPurify from "dompurify";
import { marked } from "marked";
import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import { useI18n } from "../i18n";

/** [[标题]]：引用规则书里这个标题下的一节。 */
const REF = /\[\[([^[\]]+)\]\]/g;
const HEADING = /^(#{1,6})\s+(.+?)\s*#*\s*$/;

export function plainTitle(raw: string): string {
  return raw.replace(/\*/g, "").trim();
}

/** 标题的锚点 id（中文原样保留）。 */
export function slug(title: string): string {
  return "h-" + plainTitle(title).replace(/\s+/g, "-");
}

export type Heading = { level: number; title: string; id: string };

export function headings(md: string): Heading[] {
  const out: Heading[] = [];
  for (const line of md.split("\n")) {
    const m = HEADING.exec(line);
    if (m) out.push({ level: (m[1] ?? "#").length, title: plainTitle(m[2] ?? ""), id: slug(m[2] ?? "") });
  }
  return out;
}

/** 规则书里一个标题下的一节（不含标题本身，到下一个同级或更高级的标题为止）。没有这个标题时是 null。 */
export function section(md: string, title: string): string | null {
  const lines = md.split("\n");
  const want = plainTitle(title);
  let start = -1;
  let level = 0;
  for (let i = 0; i < lines.length; i++) {
    const m = HEADING.exec(lines[i] ?? "");
    if (!m) continue;
    const lv = (m[1] ?? "#").length;
    if (start < 0) {
      if (plainTitle(m[2] ?? "") === want) {
        start = i + 1;
        level = lv;
      }
    } else if (lv <= level) {
      return lines.slice(start, i).join("\n").trim();
    }
  }
  return start < 0 ? null : lines.slice(start).join("\n").trim();
}

/** Markdown 转成安全的 HTML。标题带锚点；[[标题]] 变成指向规则书那一节的链接（refBase 是规则书页面的地址）。 */
export function toHtml(md: string, refBase = ""): string {
  const withRefs = md.replace(REF, (_m, t: string) => `[${t.trim()}](${refBase}#${encodeURIComponent(slug(t))})`);
  const renderer = new marked.Renderer();
  renderer.heading = ({ tokens, depth }) => {
    const text = renderer.parser.parseInline(tokens);
    const raw = tokens.map((x) => ("text" in x ? String(x.text) : "")).join("");
    return `<h${depth} id="${slug(raw)}">${text}</h${depth}>\n`;
  };
  const html = marked.parse(withRefs, { renderer, async: false, gfm: true, breaks: true });
  return DOMPurify.sanitize(html);
}

export function Markdown({ text, refBase = "" }: { text: string; refBase?: string }) {
  const html = useMemo(() => toHtml(text, refBase), [text, refBase]);
  return <div className="sk-md" dangerouslySetInnerHTML={{ __html: html }} />;
}

/** 建卡页上的说明用到的规则书：正文、规则书页面的地址，和“在侧边打开某一节”（没有时就地展开）。 */
type Book = { text: string; href: string; open?: (title: string) => void };
export const HandbookContext = createContext<Book>({ text: "", href: "" });

/** 提供规则书；说明里的 [[标题]] 点了以后在右边的侧栏里显示那一节。 */
export function HandbookProvider({ text, href, children }: { text: string; href: string; children: ReactNode }) {
  const { t } = useI18n();
  const [shown, setShown] = useState<string | null>(null);
  const value = useMemo(() => ({ text, href, open: setShown }), [text, href]);
  const body = shown === null ? null : section(text, shown);
  return (
    <HandbookContext.Provider value={value}>
      {children}
      {shown !== null && (
        <aside className="sk-drawer sk-ref-drawer" aria-label={t("handbook.title")}>
          <div className="sk-drawer-head">
            <h3>{shown}</h3>
            <button type="button" className="sk-link" onClick={() => setShown(null)}>
              {t("play.close")}
            </button>
          </div>
          {body === null ? <p className="sk-hint">{t("handbook.missing", { title: shown })}</p> : <Markdown text={body} refBase={href} />}
          {href && (
            <p>
              <a href={`${href}#${encodeURIComponent(slug(shown))}`} target="_blank" rel="noreferrer">
                {t("handbook.open")}
              </a>
            </p>
          )}
        </aside>
      )}
    </HandbookContext.Provider>
  );
}

/** 一段说明：普通文字原样显示，[[标题]] 变成一个小链接“规则书：标题”，点了在侧栏显示规则书里那一节。 */
export function Described({ text, className = "sk-field-desc" }: { text: string | null | undefined; className?: string }) {
  const { t } = useI18n();
  const book = useContext(HandbookContext);
  if (!text) return null;
  const parts: ReactNode[] = [];
  const refs: string[] = [];
  let last = 0;
  for (const m of text.matchAll(REF)) {
    parts.push(text.slice(last, m.index));
    refs.push((m[1] ?? "").trim());
    last = (m.index ?? 0) + m[0].length;
  }
  parts.push(text.slice(last));
  const plain = parts.join("").trim();
  return (
    <span className={className}>
      {plain}
      {refs.map((r) =>
        book.open ? (
          <button key={r} type="button" className="sk-link sk-ref-link" onClick={() => book.open?.(r)}>
            {t("handbook.ref", { title: r })}
          </button>
        ) : (
          <details key={r} className="sk-ref">
            <summary>{t("handbook.ref", { title: r })}</summary>
            <Markdown text={section(book.text, r) ?? ""} refBase={book.href} />
          </details>
        ),
      )}
    </span>
  );
}
