import { docsCatalog, type DocEntry } from "./docs";

/** 悬停提示的一条：签名、说明、各参数（名字、说明）。文字都是翻译键，显示时再翻译。 */
export type Doc = { sig: string; desc: string; params?: [string, string][] };

function asDoc(d: DocEntry): Doc {
  return { sig: d.sig, desc: d.desc, params: (d.params ?? []).map(([p, k]) => [p, k] as [string, string]) };
}

function find(category: DocEntry["category"], name: string): Doc | null {
  const d = docsCatalog().find((x) => x.category === category && x.name === name);
  return d ? asDoc(d) : null;
}

/** 检定的代码：各项和结果条件里能用的变量（只在编辑检定时用）。 */
export function checkDocs(): Record<string, Doc> {
  return Object.fromEntries(docsCatalog().filter((d) => d.category === "check").map((d) => [d.name, asDoc(d)]));
}

/**
 * 光标下这个名字的说明（来自语法手册的目录，后端从公式语言的定义生成）。word 是带点的整个名字（self.add），
 * call 是它所在的调用（写在 placement( … ) 里的参数名时是 placement），keyword 表示它后面紧跟着单个 =（是参数名或设置项的名字）。
 */
export function builtinDoc(word: string, call: string | null, keyword: boolean): { doc: Doc; param?: string } | null {
  if (keyword && call) {
    const c = find("shape", call);
    if (c?.params?.some(([p]) => p === word)) return { doc: c, param: word };
  }
  const [head, ...rest] = word.split(".");
  if (rest.length === 1 && head !== "this") {
    const v = find("verb", rest[0]!);
    if (v) return { doc: v };
  }
  if (rest.length) return null;
  if (keyword) {
    const s = find("config", word);
    if (s) return { doc: s };
  }
  const d = find("shape", word) ?? find("function", word) ?? find("variable", word) ?? find("config", word);
  return d ? { doc: d } : null;
}
