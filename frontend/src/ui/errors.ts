import { ApiError } from "../api/client";
import { translate, type Lang } from "../i18n";

/** 把消息代码渲染成当前语言的文字。没有翻译的代码原样显示，便于发现遗漏。 */
export function describeError(lang: Lang, err: unknown): string {
  if (err instanceof ApiError) {
    const head = translateCode(lang, err.body.code, err.body.params);
    const probs = (err.body.problems ?? []).slice(0, 8).map((p) => {
      const msg = translateCode(lang, p.code, p.params);
      return p.path ? `${msg} (${p.path})` : msg;
    });
    return [head, ...probs].join("\n");
  }
  return err instanceof Error ? err.message : String(err);
}

export function translateCode(lang: Lang, code: string, params?: Record<string, unknown>): string {
  const key = `codes.${code}`;
  const text = translate(lang, key, stringify(params));
  if (text !== key) return text;
  const extra = params && Object.keys(params).length ? ` ${JSON.stringify(params)}` : "";
  return `${code}${extra}`;
}

function stringify(params?: Record<string, unknown>): Record<string, string> | undefined {
  if (!params) return undefined;
  return Object.fromEntries(Object.entries(params).map(([k, v]) => [k, typeof v === "string" ? v : JSON.stringify(v)]));
}
