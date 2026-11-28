/** 角色卡文件：建卡页上整套卡（全部角色）导出成 JSON、再导入回来。和提交、角色库用的是同一份数据（每张卡的模板名和卡上内容）。 */

export type SheetRecord = { template: string; sheet: Record<string, unknown> };

/** 文件里的标记：认得出是这个程序导出的角色卡。 */
const KIND = "smartkeeper.character";
const VERSION = 1;

export function sheetFileText(sheets: readonly SheetRecord[]): string {
  return JSON.stringify({ kind: KIND, version: VERSION, exported_at: new Date().toISOString(), sheets }, null, 2) + "\n";
}

/** 导出的文件名：角色名连起来，没有名字就叫 character。去掉文件名里不能用的字符。 */
export function sheetFileName(names: readonly string[]): string {
  const base = names.map((n) => n.trim()).filter(Boolean).join("_").replace(/[\\/:*?"<>|]/g, "") || "character";
  return `${base}.json`;
}

export type ImportResult = { sheets: SheetRecord[]; skipped: number };

/** 读不懂的文件：bad 是不是 JSON、不是角色卡；none 是里面没有这套规则书要玩家建的卡。 */
export class SheetFileError extends Error {
  constructor(readonly code: "bad" | "none") {
    super(code);
  }
}

const isObject = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

/**
 * 读角色卡文件。也认只有卡的数组（[{template, sheet}, ...]）。
 * 只留这套规则书要玩家建的卡，每种卡最多留到规则书允许的张数（多的算跳过），不够最少张数的补空白卡。
 * 卡上的内容不在这里检查：填进表单以后照常算数值、找问题，提交时服务器再查一遍。
 */
export function readSheetFile(text: string, playerEntities: readonly { template: string; min: number; max: number }[]): ImportResult {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    throw new SheetFileError("bad");
  }
  const list = Array.isArray(data) ? data : isObject(data) && Array.isArray(data.sheets) ? data.sheets : null;
  if (!list) throw new SheetFileError("bad");
  const records = list.filter((x): x is SheetRecord => isObject(x) && typeof x.template === "string" && isObject(x.sheet));
  if (records.length === 0 && list.length > 0) throw new SheetFileError("bad");
  const out: SheetRecord[] = [];
  let skipped = list.length - records.length;
  const count = (t: string) => out.filter((x) => x.template === t).length;
  for (const r of records) {
    const pe = playerEntities.find((x) => x.template === r.template);
    if (!pe || count(r.template) >= pe.max) skipped += 1;
    else out.push({ template: r.template, sheet: r.sheet });
  }
  if (out.length === 0) throw new SheetFileError("none");
  // 按规则书里卡的顺序排，缺的补空白卡
  const sorted: SheetRecord[] = [];
  for (const pe of playerEntities) {
    const mine = out.filter((x) => x.template === pe.template);
    sorted.push(...mine);
    for (let i = mine.length; i < pe.min; i++) sorted.push({ template: pe.template, sheet: { name: "", fields: {}, groups: {} } });
  }
  return { sheets: sorted, skipped };
}
