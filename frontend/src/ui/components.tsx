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

export function formatGameTime(start: string | null | undefined, minutes: number, lang: string): string {
  if (!start) return `+${minutes}m`;
  const d = new Date(start);
  if (Number.isNaN(d.getTime())) return `+${minutes}m`;
  d.setMinutes(d.getMinutes() + minutes);
  return d.toLocaleString(lang === "zh" ? "zh-CN" : "en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
