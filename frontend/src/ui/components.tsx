import { useEffect, useRef, useState, type ReactNode } from "react";
import { useI18n } from "../i18n";
import { describeError, translateCode } from "./errors";

export function ErrorBox({ error }: { error: unknown }) {
  const { lang } = useI18n();
  if (!error) return null;
  return (
    <div className="sk-error" role="alert">
      {describeError(lang, error)}
    </div>
  );
}

export function LangSwitch({ onChange }: { onChange?: (l: "zh" | "en") => void }) {
  const { t, lang, setLang } = useI18n();
  const next = lang === "zh" ? "en" : "zh";
  return (
    <button
      className="sk-link"
      onClick={() => {
        setLang(next);
        onChange?.(next);
      }}
    >
      {t(next === "zh" ? "lang.zh" : "lang.en")}
    </button>
  );
}

export function Tabs<K extends string>({
  tabs,
  active,
  onChange,
}: {
  tabs: { key: K; label: string; badge?: number }[];
  active: K;
  onChange: (k: K) => void;
}) {
  return (
    <nav className="sk-tabs">
      {tabs.map((tb) => (
        <button key={tb.key} className={tb.key === active ? "active" : ""} onClick={() => onChange(tb.key)}>
          {tb.label}
          {tb.badge ? <span className="sk-badge">{tb.badge}</span> : null}
        </button>
      ))}
    </nav>
  );
}

/** 列表里的一项上移、下移。只改排列，不改含义（会影响计算的列表在旁边另有说明）。 */
export function Mover({ index, count, onMove }: { index: number; count: number; onMove: (from: number, to: number) => void }) {
  const { t } = useI18n();
  return (
    <span className="sk-mover">
      <button type="button" className="sk-link" disabled={index === 0} title={t("common.move_up")} aria-label={t("common.move_up")} onClick={() => onMove(index, index - 1)}>
        ↑
      </button>
      <button type="button" className="sk-link" disabled={index >= count - 1} title={t("common.move_down")} aria-label={t("common.move_down")} onClick={() => onMove(index, index + 1)}>
        ↓
      </button>
    </span>
  );
}

/** 把列表里 from 位置的一项挪到 to。 */
export function moved<T>(list: T[], from: number, to: number): T[] {
  if (to < 0 || to >= list.length) return list;
  const out = [...list];
  const [x] = out.splice(from, 1);
  out.splice(to, 0, x as T);
  return out;
}

/** 可折叠的一段。默认展开；标题点一下收起。 */
export function Fold({ title, hint, level = 3, children }: { title: ReactNode; hint?: ReactNode; level?: 3 | 4 | 5; children: ReactNode }) {
  const [open, setOpen] = useState(true);
  const H = `h${level}` as "h3" | "h4" | "h5";
  return (
    <details className="sk-fold" open={open} onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary>
        <H>{title}</H>
      </summary>
      {hint && <p className="sk-hint">{hint}</p>}
      {children}
    </details>
  );
}

export function Section({ title, children, actions }: { title: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <section className="sk-section">
      <header>
        <h2>{title}</h2>
        {actions}
      </header>
      {children}
    </section>
  );
}

/** 公式输入框：实时校验，补全字段名。不合法的公式标红。 */
export function FormulaInput({
  value,
  onChange,
  validate,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  validate: (formula: string) => Promise<{ problems: { code: string; params?: Record<string, unknown> }[]; names: string[] }>;
}) {
  const { t, lang } = useI18n();
  const [problems, setProblems] = useState<string[]>([]);
  const [names, setNames] = useState<string[]>([]);
  const [focus, setFocus] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => {
    window.clearTimeout(timer.current);
    if (!value.trim()) {
      setProblems([]);
      return;
    }
    timer.current = window.setTimeout(() => {
      validate(value)
        .then((r) => {
          setProblems(r.problems.map((p) => translateCode(lang, p.code, p.params)));
          setNames(r.names);
        })
        .catch(() => setProblems([]));
    }, 300);
    return () => window.clearTimeout(timer.current);
  }, [value, validate]);
  const word = /[\p{L}_][\p{L}\p{N}_.]*$/u.exec(value)?.[0] ?? "";
  const suggestions = focus && word ? names.filter((n) => n.startsWith(word) && n !== word).slice(0, 6) : [];
  return (
    <span className="sk-formula">
      <input
        className={problems.length ? "invalid" : ""}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        onFocus={() => setFocus(true)}
        onBlur={() => window.setTimeout(() => setFocus(false), 150)}
        spellCheck={false}
      />
      {suggestions.length > 0 && (
        <span className="sk-suggest">
          {suggestions.map((s) => (
            <button key={s} type="button" onMouseDown={() => onChange(value.slice(0, value.length - word.length) + s)}>
              {s}
            </button>
          ))}
        </span>
      )}
      {problems.length > 0 && <small className="sk-invalid">{t("formula.invalid")}: {problems.join("; ")}</small>}
    </span>
  );
}

/** 简单的 Markdown 显示：标题、列表、段落。足够阅读规则书和剧本。 */
export function MarkdownView({ text }: { text: string }) {
  const lines = text.split("\n");
  return (
    <div className="sk-md">
      {lines.map((line, i) => {
        const h = /^(#{1,4})\s+(.*)$/.exec(line);
        if (h) {
          const level = Math.min(4, (h[1] ?? "#").length + 1);
          const Tag = `h${level}` as "h2" | "h3" | "h4" | "h5";
          return <Tag key={i}>{h[2]}</Tag>;
        }
        if (/^\s*[-*]\s+/.test(line)) return <div key={i} className="li">{line.replace(/^\s*[-*]\s+/, "• ")}</div>;
        if (!line.trim()) return <div key={i} className="gap" />;
        return <p key={i}>{line}</p>;
      })}
    </div>
  );
}

/** 游戏内时刻：剧本的起始时刻加上经过的秒数。 */
export function formatGameTime(start: string | null | undefined, seconds: number, lang: string): string {
  const d = start ? new Date(start) : null;
  if (!d || Number.isNaN(d.getTime())) return `+${seconds}s`;
  d.setSeconds(d.getSeconds() + seconds);
  return d.toLocaleString(lang === "zh" ? "zh-CN" : "en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/** 时长：“1 分 20 秒”。 */
export function formatDuration(t: (k: string, p?: Record<string, string>) => string, seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return t("time.s", { s: String(s) });
  if (s < 3600) return t("time.ms", { m: String(Math.floor(s / 60)), s: String(s % 60) });
  return t("time.hm", { h: String(Math.floor(s / 3600)), m: String(Math.floor((s % 3600) / 60)) });
}
