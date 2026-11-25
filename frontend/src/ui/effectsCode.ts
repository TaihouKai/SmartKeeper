/**
 * 常驻加成的代码写法：一行一条“self.<名字> = 公式”，行尾 # 后面是说明；只有 # 说明的一行是由 KP 理解的加成。
 * 存的还是效果列表（target / formula / description），这里只是在文字和列表之间转换。
 */
export type EffectLike = { description: string; target?: string | null; formula?: string | null; priority?: number | null };
export type EffectLine = { line: number; effect: EffectLike } | { line: number; error: "effects.bad_line" };

const ASSIGN = /^([A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)*)\s*=(?!=)\s*(.+)$/;

/** 引号外面的第一个 #：后面是注释。 */
function splitComment(text: string): [string, string] {
  let quote = "";
  for (let i = 0; i < text.length; i++) {
    const c = text[i]!;
    if (quote) {
      if (c === "\\") i++;
      else if (c === quote) quote = "";
    } else if (c === '"' || c === "'") quote = c;
    else if (c === "#") return [text.slice(0, i), text.slice(i + 1)];
  }
  return [text, ""];
}

export function toCode(effects: readonly EffectLike[]): string {
  return effects
    .filter((e) => e.target || e.description.trim())  // 空白的（旧界面加了没填的）不显示
    .map((e) => {
      const note = e.description.trim();
      if (!e.target) return `# ${note}`;
      const head = e.target.includes(".") ? e.target : `self.${e.target}`;
      return `${head} = ${e.formula ?? ""}${note ? `  # ${note}` : ""}`;
    })
    .join("\n");
}

export function parseCode(text: string): EffectLine[] {
  const out: EffectLine[] = [];
  text.split("\n").forEach((raw, i) => {
    const line = i + 1;
    const [code, note] = splitComment(raw);
    const body = code.trim();
    if (!body) {
      if (note.trim()) out.push({ line, effect: { description: note.trim(), target: null, formula: null, priority: null } });
      return;
    }
    const m = ASSIGN.exec(body);
    if (!m) {
      out.push({ line, error: "effects.bad_line" });
      return;
    }
    const target = m[1]!.startsWith("self.") ? m[1]!.slice(5) : m[1]!;
    out.push({ line, effect: { description: note.trim(), target, formula: m[2]!.trim(), priority: null } });
  });
  return out;
}

/** 解析成效果列表；写错的行跳过。同一位置、同一目标的保留原来的 priority。 */
export function fromCode(text: string, old: readonly EffectLike[] = []): EffectLike[] {
  const effects = parseCode(text).flatMap((x) => ("effect" in x ? [x.effect] : []));
  return effects.map((e, i) => (old[i] && old[i]!.target === e.target ? { ...e, priority: old[i]!.priority } : e));
}
