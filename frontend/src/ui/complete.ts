/** 补全的一项：label 是显示的那一段，insert 是选中后替换光标前那个词的文本，more 表示后面还能接着点。 */
export type Suggestion = { insert: string; label: string; more: boolean };

/**
 * 光标前的词（可以带点，例如 "master." 或 "master.fi"）在全部名字里的下一段候选。
 * 只列下一段：输入 master. 时列出 master 下面的每个名字（fireball、hp……），不列 master.fireball.level 这种更深的。
 * 只能接着点、本身不是名字的（例如分组前缀）选中时直接带上点。
 */
export function suggest(names: readonly string[], word: string): Suggestion[] {
  if (!word) return [];
  const dot = word.lastIndexOf(".");
  const prefix = word.slice(0, dot + 1);
  const tail = word.slice(dot + 1);
  const known = new Set(names);
  const found = new Map<string, Suggestion>();
  for (const n of names) {
    if (!n.startsWith(prefix)) continue;
    const rest = n.slice(prefix.length);
    const seg = rest.split(".")[0] ?? "";
    if (!seg || !seg.startsWith(tail)) continue;
    const full = prefix + seg;
    const more = rest.length > seg.length;
    found.set(full, { insert: full, label: seg, more: (found.get(full)?.more ?? false) || more });
  }
  return [...found.values()]
    .map((s) => (known.has(s.insert) ? s : { ...s, insert: s.insert + "." }))
    .filter((s) => s.insert !== word)
    .sort((a, b) => Number(!a.label.startsWith(tail)) - Number(!b.label.startsWith(tail)) || a.label.localeCompare(b.label));
}
