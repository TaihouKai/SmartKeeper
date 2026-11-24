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
  ["shape", "None"],
  ["placement", "None"],
];

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
