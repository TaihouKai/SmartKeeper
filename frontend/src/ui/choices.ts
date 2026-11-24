/** 数值字段的可选值（和后端 rules/choices.py 一样）：名字=数（E=1）、数（10）、范围（1~5）。 */

export type NumberOption = { value: number; label: string | null };

const NUM = /^-?\d+(?:\.\d+)?$/;
const RANGE = /^(-?\d+(?:\.\d+)?)\s*[~～\-–]\s*(-?\d+(?:\.\d+)?)$/;

/** 全部可选的数（范围展开成整数，太大的范围不展开）；写错的项跳过。按数从小到大。 */
export function numberOptions(choices: readonly string[]): NumberOption[] {
  const out = new Map<number, NumberOption>();
  for (const raw of choices) {
    const item = raw.trim();
    const eq = item.indexOf("=");
    if (eq > 0) {
      const v = item.slice(eq + 1).trim();
      if (NUM.test(v)) out.set(Number(v), { value: Number(v), label: item.slice(0, eq).trim() });
      continue;
    }
    if (NUM.test(item)) {
      if (!out.has(Number(item))) out.set(Number(item), { value: Number(item), label: null });
      continue;
    }
    const m = RANGE.exec(item);
    if (!m) continue;
    const lo = Math.ceil(Number(m[1]));
    const hi = Math.floor(Number(m[2]));
    if (hi - lo > 500) continue;
    for (let v = lo; v <= hi; v++) if (!out.has(v)) out.set(v, { value: v, label: null });
  }
  return [...out.values()].sort((a, b) => a.value - b.value);
}

/** 这个数显示成什么：有名字显示名字（EX），没有就是数本身。 */
export function showNumber(choices: readonly string[] | undefined, value: number): string {
  const hit = choices?.length ? numberOptions(choices).find((o) => o.value === value && o.label) : undefined;
  return hit?.label ?? String(value);
}
