import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import zh from "./zh.json";
import en from "./en.json";

export type Lang = "zh" | "en";
type Table = { [k: string]: string | Table };
const tables: Record<Lang, Table> = { zh, en };

function lookup(table: Table, key: string): string | undefined {
  let cur: string | Table | undefined = table;
  for (const part of key.split(".")) {
    if (cur === undefined || typeof cur === "string") return undefined;
    cur = cur[part];
  }
  return typeof cur === "string" ? cur : undefined;
}

/** 渲染一个消息代码。参数用 {name} 占位。找不到键时返回键本身，便于发现遗漏。 */
export function translate(lang: Lang, key: string, params?: Record<string, string | number>): string {
  const raw = lookup(tables[lang], key) ?? key;
  if (!params) return raw;
  return raw.replace(/\{(\w+)\}/g, (_, name: string) => String(params[name] ?? `{${name}}`));
}

interface I18n {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (key: string, params?: Record<string, string | number>) => string;
}

const Ctx = createContext<I18n | null>(null);

function initialLang(): Lang {
  try {
    const saved = localStorage.getItem("sk.lang");
    if (saved === "zh" || saved === "en") return saved;
  } catch {
    /* storage unavailable */
  }
  return navigator.language.startsWith("zh") ? "zh" : "en";
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(initialLang);
  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    try {
      localStorage.setItem("sk.lang", l);
    } catch {
      /* storage unavailable */
    }
  }, []);
  const value = useMemo<I18n>(
    () => ({ lang, setLang, t: (key, params) => translate(lang, key, params) }),
    [lang, setLang],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useI18n(): I18n {
  const v = useContext(Ctx);
  if (!v) throw new Error("useI18n outside I18nProvider");
  return v;
}
