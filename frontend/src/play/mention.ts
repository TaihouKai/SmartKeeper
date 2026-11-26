/** 输入框里打 @ 弹出候选：找光标前正在打的 @词，选中后换成 @[名字](引用)。 */

/**
 * 光标前的 @词：@ 后面到光标之间没有空白和括号。没有在打 @词时是 null。
 * @ 前面可以紧挨着中文（“去@教会”），中文标点下的全角 ＠ 也算；紧挨着英文字母或数字时不算（a@b 这种是邮箱之类）。
 */
export function mentionQuery(text: string, caret: number): { start: number; query: string } | null {
  const before = text.slice(0, caret);
  const m = /(^|[^A-Za-z0-9])[@＠]([^\s@＠[\]()]{0,30})$/.exec(before);
  if (!m) return null;
  return { start: caret - m[2]!.length - 1, query: m[2]! };
}

/** 候选：名字里含有打的字的（不分大小写），以它开头的排在前面。 */
export function filterMentions<T extends { label: string }>(list: T[], query: string, limit = 8): T[] {
  const q = query.toLowerCase();
  return list
    .filter((x) => x.label.toLowerCase().includes(q))
    .sort((a, b) => Number(!a.label.toLowerCase().startsWith(q)) - Number(!b.label.toLowerCase().startsWith(q)))
    .slice(0, limit);
}

/** 把 start 到光标的 @词换成 insert（后面补一个空格）；返回新文字和新的光标位置。 */
export function insertMention(text: string, start: number, caret: number, insert: string): { text: string; caret: number } {
  const out = `${text.slice(0, start)}${insert} ${text.slice(caret).replace(/^ /, "")}`;
  return { text: out, caret: start + insert.length + 1 };
}
