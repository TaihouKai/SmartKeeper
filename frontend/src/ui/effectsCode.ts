/** 旧格式的常驻加成（一条一条的列表）第一次打开时显示成代码；之后存的就是代码（bonus）。 */
export type EffectLike = { description: string; target?: string | null; formula?: string | null; priority?: number | null };

const OPS = ["+", "-", "*", "/"];

/** target 的新值公式写成 self.target = …；能写成 self.target += x 的写成那样（公式就是“自己 运算 别的”）。 */
function line(target: string, formula: string): string {
  const head = target.includes(".") ? target : `self.${target}`;
  const f = formula.trim();
  for (const me of [`self.${target}`, target]) {
    for (const op of OPS) {
      const pre = `${me} ${op} `;
      if (f.startsWith(pre)) {
        const rest = f.slice(pre.length);
        // 只在后面没有更低优先级的运算时改写（避免 a * 2 + 1 写成 a *= 2 + 1）
        const low = op === "*" || op === "/" ? /(^|[^*/<>=!])\s[+-]\s/ : /\sif\s|\sand\s|\sor\s|[<>=]=?|\s-\s/;
        if (!low.test(` ${rest} `) && !/\bif\b/.test(rest)) return `${head} ${op}= ${rest}`;
      }
    }
  }
  return `${head} = ${f}`;
}

export function toCode(effects: readonly EffectLike[]): string {
  return effects
    .filter((e) => e.target || e.description.trim())
    .map((e) => {
      const note = e.description.trim();
      if (!e.target) return `# ${note}`;
      return `${line(e.target, e.formula ?? "")}${note ? `  # ${note}` : ""}`;
    })
    .join("\n");
}
