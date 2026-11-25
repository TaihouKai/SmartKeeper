/** 技能设置的预填：这个分组用得上的每一项都写出来（没写的补在后面，带说明），已有的不动。和后端 rules/skillconfig.py 的 KEYS 对应。 */

type GroupLike = { timing?: boolean; placements?: boolean; shapes?: { allowed?: string[] } | null };

const DEFAULTS: [string, string][] = [
  ["target", '"single"'],
  ["range", "None"],
  ["visible", "False"],
  ["requires", "None"],
  ["noise", "None"],
  ["cast_time", "None"],
  ["cooldown", "None"],
  ["check", "None"],
  ["difficulty", "None"],
  ["reactions", "[]"],
  ["hit", "None"],
  ["shape", "None"],
  ["placement", "None"],
];

/** 设置里还能写、但不预填的项（少用）。 */
export const EXTRA_CONFIG_KEYS = ["auto_level", "save", "affects", "aura"];
/** 用技能时引擎给的数：设置的公式里能用前两个，命中条件 hit 到 opposed，技能脚本全部（和后端 skillconfig 的 *_VARS 对应）。 */
export const OUTCOME_VARS = ["distance", "unseen", "level", "opp_level", "opposed", "saved", "reacting", "ally"];
/** 检定的代码能写的项、条件里能用的变量（和后端 checkconfig 的 KEYS、VARS 对应）。 */
export const CHECK_KEYS = ["label", "dice", "target", "success", "level", "levels", "opposed_by"];
export const CHECK_VARS = ["roll", "natural", "target", "difficulty", "distance", "opp_roll", "opp_target", "self.template", "opponent.template"];

export function configKeys(group: GroupLike): string[] {
  return DEFAULTS.map(([k]) => k).filter((k) => {
    if (k === "cast_time" || k === "cooldown") return group.timing !== false;
    if (k === "shape") return (group.shapes?.allowed ?? []).length > 0;
    if (k === "placement") return !!group.placements;
    return true;
  });
}

/** 补上没写的项。t 用来写每一项的说明注释（config.c.<名字>）。 */
export function fillConfig(text: string, group: GroupLike, t: (k: string) => string): string {
  const have = new Set([...text.matchAll(/^\s*([A-Za-z_]\w*)\s*=/gm)].map((m) => m[1]));
  const missing = configKeys(group).filter((k) => !have.has(k));
  if (!missing.length) return text;
  const width = Math.max(...missing.map((k) => `${k} = ${DEFAULTS.find(([x]) => x === k)![1]}`.length));
  const lines = missing.map((k) => {
    const line = `${k} = ${DEFAULTS.find(([x]) => x === k)![1]}`;
    return `${line.padEnd(width)}  # ${t(`config.c.${k}`)}`;
  });
  const head = text.trimEnd();
  return head ? `${head}\n${lines.join("\n")}` : lines.join("\n");
}

/** 检定的代码：没写的项补上（带说明）。和后端 rules/checkconfig.py 的 KEYS 对应。 */
const CHECK_DEFAULTS: [string, string][] = [
  ["label", '""'],
  ["dice", "1d20"],
  ["target", "0"],
  ["success", "roll > 10 + difficulty"],
  ["opposed_by", "None"],
];

export function fillCheck(text: string, t: (k: string) => string): string {
  const have = new Set([...text.matchAll(/^\s*([A-Za-z_]\w*)\s*=/gm)].map((m) => m[1]));
  const missing = CHECK_DEFAULTS.filter(([k]) => !have.has(k));
  if (!missing.length) return text;
  const width = Math.max(...missing.map(([k, v]) => `${k} = ${v}`.length));
  const lines = missing.map(([k, v]) => `${`${k} = ${v}`.padEnd(width)}  # ${t(`check.c.${k}`)}`);
  const head = text.trimEnd();
  return head ? `${head}\n${lines.join("\n")}` : lines.join("\n");
}

/** 用途的设置：自己写了的项覆盖条目的（只看一行一项的写法），没写的沿用条目的。 */
export function mergeConfig(base: string, own: string): string {
  if (!base.trim()) return own;
  if (!own.trim()) return base;
  const key = (ln: string) => /^([A-Za-z_]\w*)\s*=(?!=)/.exec(ln)?.[1];
  const mine = new Set(own.split("\n").map(key).filter(Boolean));
  const kept = base.split("\n").filter((ln) => {
    const k = key(ln);
    return k === undefined || !mine.has(k);
  });
  return [...kept, own].join("\n");
}
