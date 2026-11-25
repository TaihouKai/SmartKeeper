import type { Schemas } from "../../api/client";
import type { Scope } from "../fieldCard";

export type Pack = Schemas["RulePack"];
export type Template = Schemas["EntityTemplate"];
export type Field = Schemas["FieldDef"];
export type Group = Schemas["GroupDef"];
type T = (k: string, params?: Record<string, string>) => string;

export const REQUIRED_DERIVED = ["perception_radius", "concealment", "move_speed", "fly_multiplier", "fly_speed", "hear_multiplier", "hear_distance"];
export const FLY_FIELD = "can_fly";
export const HP_FIELD = "hp";
const REQUIRED_FIELDS = ["appearance", FLY_FIELD, HP_FIELD];
const DEFAULT_FORMULA: Record<string, string> = { concealment: "1", fly_multiplier: "1", fly_speed: "fly_multiplier * move_speed", hear_multiplier: "1" };
const DEFAULT_UNIT: Record<string, string> = { perception_radius: "m", move_speed: "m/min", fly_speed: "m/min", hear_distance: "m" };

/** 引擎必需项的默认显示名（按界面语言），也是它们显示名框里的提示。 */
function defaultLabel(t: T, name: string): string {
  return t(`rules.default_label.${name}`);
}

export function blankPack(t: T): Pack {
  return {
    world: { name: "", description: "", canon: "", reference_sites: [] },
    templates: [blankTemplate("character", t)],
    player_entities: [{ template: "character", min: 1, max: 1 }],
    formulas: [],
    tables: [],
    checks: [],
    rules_text: "",
    samples: [],
    insights: [],
    handbook: "",
    params: [],
  };
}

export function blankTemplate(name: string, t: T): Template {
  return {
    name,
    label: "",
    description: "",
    appearance_field: "appearance",
    fields: [
      { name: "appearance", label: defaultLabel(t, "appearance"), description: "", kind: "text", cls: "player", required: true, hidden: false, choices: [], vital: false },
      { name: FLY_FIELD, label: defaultLabel(t, FLY_FIELD), description: "", kind: "boolean", cls: "player", required: true, hidden: false, choices: [], vital: false },
      { name: HP_FIELD, label: defaultLabel(t, HP_FIELD), description: "", kind: "resource", cls: "runtime", min: "0", initial: "10", required: true, hidden: false, choices: [], vital: true },
    ],
    groups: [],
    damage_taken: "",
    stealth: "",
    search: "",
    on_death: "",
    derived: REQUIRED_DERIVED.map((n) => ({
      name: n,
      label: defaultLabel(t, n),
      formula: DEFAULT_FORMULA[n] ?? "",
      unit: DEFAULT_UNIT[n] ?? null,
      hidden: false,
    })),
  };
}

export function blankGroup(): Group {
  return { name: "", label: "", description: "", fields: [], presets: [], min_count: 0, max_count: null, effects: true, shapes: { allowed: [] }, hidden: false, placements: true, timing: true, reactions: true, damage_kind: "", use_templates: [], reveal: "", reveal_fields: [], uses: false };
}

/** 以前存的规则包可能缺少后来新增的引擎必需项（能否飞行字段、飞行速度等推导值）：打开时补上默认的；必需项的显示名空着就填默认的。 */
export function withEngineDefaults(p: Pack, t: T): Pack {
  const blank = blankTemplate("x", t);
  const named = <X extends { name: string; label?: string }>(x: X): X => (x.label ? x : { ...x, label: defaultLabel(t, x.name) });
  return {
    ...p,
    templates: p.templates.map((tpl) => {
      const fields = tpl.fields ?? [];
      const derived = tpl.derived ?? [];
      const missing = (blank.fields ?? []).filter((f) => f.name !== "appearance" && !fields.some((x) => x.name === f.name));
      const allFields = [...fields, ...missing];
      const allDerived = [...derived, ...(blank.derived ?? []).filter((d) => !derived.some((x) => x.name === d.name))];
      return {
        ...tpl,
        fields: allFields.map((f) => (REQUIRED_FIELDS.includes(f.name) ? named(f) : f)),
        derived: allDerived.map((d) => (REQUIRED_DERIVED.includes(d.name) ? named(d) : d)),
      };
    }),
  };
}

/** 改了模板 ID：建角实体和例题里引用它的地方跟着改。 */
export function renameTemplate(pack: Pack, i: number, next: Template): Pack {
  const prev = pack.templates[i]?.name;
  const templates = pack.templates.map((x, j) => (j === i ? next : x));
  if (!prev || prev === next.name) return { ...pack, templates };
  return {
    ...pack,
    templates,
    player_entities: pack.player_entities.map((pe) => (pe.template === prev ? { ...pe, template: next.name } : pe)),
    samples: (pack.samples ?? []).map((sm) => (sm.template === prev ? { ...sm, template: next.name } : sm)),
  };
}

// ---------------- 路径：和后端报问题用的一样，例如 templates[0].groups[1].presets[2].script ----------------

export type Seg = string | number;

export function parsePath(path: string): Seg[] {
  const out: Seg[] = [];
  for (const part of path.split(".")) {
    if (!part) continue;
    const m = /^([^[\]]+)((?:\[\d+\])*)$/.exec(part);
    if (!m) {
      out.push(part);
      continue;
    }
    out.push(m[1]!);
    for (const idx of (m[2] ?? "").matchAll(/\[(\d+)\]/g)) out.push(Number(idx[1]));
  }
  return out;
}

export function getAt(obj: unknown, path: string): unknown {
  let cur: unknown = obj;
  for (const s of parsePath(path)) {
    if (cur === null || typeof cur !== "object") return undefined;
    cur = (cur as Record<string | number, unknown>)[s];
  }
  return cur;
}

/** 不改原对象，返回改了这一处的新对象（沿路复制）。 */
export function setAt<X>(obj: X, path: string, value: unknown): X {
  const segs = parsePath(path);
  const go = (cur: unknown, i: number): unknown => {
    if (i === segs.length) return value;
    const s = segs[i]!;
    if (typeof s === "number") {
      const arr = Array.isArray(cur) ? [...(cur as unknown[])] : [];
      arr[s] = go(arr[s], i + 1);
      return arr;
    }
    const rec = cur && typeof cur === "object" ? { ...(cur as Record<string, unknown>) } : {};
    rec[s] = go(rec[s], i + 1);
    return rec;
  };
  return go(obj, 0) as X;
}

// ---------------- 左边目录里选中的一节 ----------------

export type Sel =
  | { k: "world" }
  | { k: "fields"; t: number }
  | { k: "derived"; t: number }
  | { k: "group"; t: number; g: number }
  | { k: "players" }
  | { k: "formulas" }
  | { k: "tables" }
  | { k: "checks" }
  | { k: "text" }
  | { k: "insights" }
  | { k: "handbook" }
  | { k: "params" }
  | { k: "samples" };

export function selKey(s: Sel): string {
  if (s.k === "fields" || s.k === "derived") return `${s.k}:${s.t}`;
  if (s.k === "group") return `group:${s.t}:${s.g}`;
  return s.k;
}

/** 路径落在哪一节（点问题、点查找结果时跳过去）。 */
export function selForPath(path: string): Sel {
  const s = parsePath(path);
  if (s[0] === "templates" && typeof s[1] === "number") {
    if (s[2] === "groups" && typeof s[3] === "number") return { k: "group", t: s[1], g: s[3] };
    if (s[2] === "derived") return { k: "derived", t: s[1] };
    return { k: "fields", t: s[1] };
  }
  const map: Record<string, Sel> = {
    world: { k: "world" },
    player_entities: { k: "players" },
    formulas: { k: "formulas" },
    tables: { k: "tables" },
    checks: { k: "checks" },
    rules_text: { k: "text" },
    insights: { k: "insights" },
    handbook: { k: "handbook" },
    params: { k: "params" },
    samples: { k: "samples" },
  };
  return map[String(s[0])] ?? { k: "world" };
}

// ---------------- IDE 里能打开的文档：一段公式或技能脚本 ----------------

export type Doc = {
  path: string;
  /** entry：一个条目（上面是技能设置，下面是技能脚本）；script / config 只用于查找，打开时换成它们所在的条目 */
  kind: "entry" | "script" | "config" | "check" | "formula";
  /** 校验和补全用：在哪个模板、哪个分组的条目里，什么范围 */
  template: string | null;
  inEntry?: string;
  scope?: Scope;
  /** 条目这一行（脚本试运行用）：模板序号、分组序号、行号；u 是这一条的第几个用途 */
  entry?: { t: number; g: number; r: number; u?: number };
};

const TEMPLATE_FORMULA_KEYS = new Set(["min", "max", "initial", "per_minute"]);

/** 这个路径是不是一段能在 IDE 里打开的公式或脚本；是的话返回校验它需要的上下文。 */
export function docFor(pack: Pack, path: string): Doc | null {
  const s = parsePath(path);
  if (s[0] === "formulas" && typeof s[1] === "number" && s[2] === "formula") return { path, kind: "formula", template: null, scope: "any_entity" };
  if (s[0] === "checks" && typeof s[1] === "number") {
    return s[2] === "config" ? { path, kind: "check", template: null, scope: "check" } : null;
  }
  if (s[0] !== "templates" || typeof s[1] !== "number") return null;
  const tpl = pack.templates[s[1]];
  if (!tpl) return null;
  const template = tpl.name;
  if (s[2] === "derived" && s[4] === "formula") return { path, kind: "formula", template };
  if (s[2] === "damage_taken") return { path, kind: "formula", template, scope: "damage" };
  if (s[2] === "stealth" || s[2] === "search") return { path, kind: "formula", template, scope: s[2] };
  if (s[2] === "on_death") return { path, kind: "formula", template, scope: "script" };
  if (s[2] === "fields" && TEMPLATE_FORMULA_KEYS.has(String(s[4]))) return { path, kind: "formula", template };
  if (s[2] !== "groups" || typeof s[3] !== "number") return null;
  const g = tpl.groups?.[s[3]];
  if (!g) return null;
  const inEntry = g.name;
  if (s[4] === "fields" && TEMPLATE_FORMULA_KEYS.has(String(s[6]))) return { path, kind: "formula", template, inEntry };
  // 用途的模板：和条目一样有设置和脚本
  if (s[4] === "use_templates" && typeof s[5] === "number") {
    if (!g.use_templates?.[s[5]]) return null;
    if (s.length === 6) return { path, kind: "entry", template, inEntry };
    if (s[6] === "script") return { path, kind: "script", template, inEntry, scope: "script" };
    if (s[6] === "config") return { path, kind: "config", template, inEntry, scope: "config" };
    return null;
  }
  if (s[4] !== "presets" || typeof s[5] !== "number") return null;
  const entry = { t: s[1], g: s[3], r: s[5] };
  if (s.length === 6) return g.presets?.[s[5]] ? { path, kind: "entry", template, inEntry, entry } : null;
  // 固定条目的一个用途
  if (s[6] === "uses" && typeof s[7] === "number") {
    const u = { ...entry, u: s[7] };
    if (!g.presets?.[s[5]]?.uses?.[s[7]]) return null;
    if (s.length === 8) return { path, kind: "entry", template, inEntry, entry: u };
    if (s[8] === "script") return { path, kind: "script", template, inEntry, scope: "script", entry: u };
    if (s[8] === "config") return { path, kind: "config", template, inEntry, scope: "config", entry: u };
    return null;
  }
  const key = String(s[6]);
  if (key === "script") return { path, kind: "script", template, inEntry, scope: "script", entry };
  if (key === "config") return { path, kind: "config", template, inEntry, scope: "config", entry };
  if (key === "when") return { path, kind: "formula", template, entry };
  if (key === "fields" && typeof s[7] === "string") {
    const def = (g.fields ?? []).find((f) => f.name === s[7]);
    if (def?.kind === "formula") return { path, kind: "formula", template, inEntry, scope: "dice", entry };
    return null;
  }
  if (key === "effects" && s[8] === "formula") return { path, kind: "formula", template, inEntry, entry };
  return null;
}

/** 在 IDE 里打开时用的路径：条目的设置和脚本都打开整个条目。 */
export function openPath(path: string): string {
  const m = /^(.*\.(?:presets\[\d+\](?:\.uses\[\d+\])?|use_templates\[\d+\]))\.(config|script)$/.exec(path);
  return m ? m[1]! : path;
}

/** 规则包里所有的公式和脚本（查找引用用）：路径和文本。 */
export function allFormulas(pack: Pack): { path: string; text: string }[] {
  const out: { path: string; text: string }[] = [];
  const walk = (x: unknown, path: string) => {
    if (typeof x === "string") {
      if (x.trim() && docFor(pack, path)) out.push({ path, text: x });
      return;
    }
    if (Array.isArray(x)) x.forEach((v, i) => walk(v, `${path}[${i}]`));
    else if (x && typeof x === "object") for (const [k, v] of Object.entries(x)) walk(v, path ? `${path}.${k}` : k);
  };
  walk(pack, "");
  return out;
}

/** 把问题路径（templates[0].fields[2]）换成看得懂的名字（模板 hero › 字段 hp）。 */
export function describePath(t: (k: string) => string, pack: Pack, path: string): string[] {
  if (!path || path === ".") return [];
  let obj: unknown = pack;
  const out: string[] = [];
  for (const seg of path.split(".")) {
    const m = /^(\w+)\[(\d+)\]$/.exec(seg);
    const key = m?.[1] ?? seg;
    const label = t(`rules.path.${key}`);
    const known = label !== `rules.path.${key}`;
    obj = obj && typeof obj === "object" ? (obj as Record<string, unknown>)[key] : undefined;
    if (m) {
      const idx = Number(m[2]);
      obj = Array.isArray(obj) ? obj[idx] : undefined;
      const rec = obj && typeof obj === "object" ? (obj as Record<string, unknown>) : {};
      const name = typeof rec.label === "string" && rec.label ? rec.label : typeof rec.name === "string" && rec.name ? rec.name : `#${idx + 1}`;
      out.push(known ? `${label} ${name}` : name);
    } else {
      out.push(known ? label : seg);
    }
  }
  return out;
}

/** IDE 标签页上的短名字：最近一个有名字的那一项 · 哪一格（例如 攻击魔术 · 技能脚本）。 */
export function shortTitle(t: (k: string) => string, pack: Pack, path: string): string {
  const segs = parsePath(path);
  let obj: unknown = pack;
  let name = "";
  for (const s of segs) {
    obj = obj && typeof obj === "object" ? (obj as Record<string | number, unknown>)[s] : undefined;
    if (typeof s === "number" && obj && typeof obj === "object") {
      const r = obj as Record<string, unknown>;
      const n = (typeof r.label === "string" && r.label) || (typeof r.name === "string" && r.name) || "";
      if (n) name = n;
    }
  }
  if (typeof segs[segs.length - 1] === "number") return name || path;
  const last = String(segs[segs.length - 1] ?? "");
  const label = t(`rules.path.${last}`);
  const what = segs[segs.length - 2] === "fields" || label === `rules.path.${last}` ? last : label;
  return name ? `${name} · ${what}` : what;
}

/** 本条目里技能设置的项、技能脚本的变量：名字 -> 公式文本（悬停提示用）。 */
function entryNames(config: string, script: string): Map<string, { value: string; setting: boolean }> {
  const out = new Map<string, { value: string; setting: boolean }>();
  for (const [text, setting] of [
    [script, false],
    [config, true],
  ] as const) {
    for (const m of text.matchAll(/^[ \t]*([A-Za-z_]\w*)[ \t]*=(?!=)[ \t]*(.*)$/gm)) {
      const value = (m[2] ?? "").replace(/#.*$/, "").trim();
      if (value && value !== "None") out.set(m[1]!, { value, setting });
    }
  }
  return out;
}

/** 公式里一个名字的说明：字段、推导值、命名公式、查表、这一条的列、本条目的设置和变量。 */
export function describeName(
  t: (k: string, p?: Record<string, string>) => string,
  pack: Pack,
  doc: Doc | null,
  word: string,
  texts: { config: string; script: string } = { config: "", script: "" },
): { title: string; body: string } | null {
  const parts = word.split(".");
  const last = parts[parts.length - 1]!;
  const kind = (k: string) => t(`rules.kind.${k}`);
  const field = (f: Field, prefix: string) => ({
    title: f.label ? `${word} — ${f.label}` : word,
    body: [prefix, kind(f.kind), f.description].filter(Boolean).join(" · "),
  });
  const group = doc?.entry ? pack.templates[doc.entry.t]?.groups?.[doc.entry.g] : undefined;
  if (parts[0] === "this" && parts.length === 2 && group) {
    const f = (group.fields ?? []).find((x) => x.name === last);
    if (!f) return null;
    const v = (group.presets?.[doc!.entry!.r]?.fields ?? {})[last];
    const info = field(f, t("doc.field.this"));
    return v === undefined || v === "" ? info : { ...info, body: `${info.body} · = ${String(v)}` };
  }
  if (parts.length === 1) {
    const own = entryNames(texts.config, texts.script).get(word);
    if (own) return { title: `${word} = ${own.value}`, body: own.setting ? t(`config.c.${word}`) : t("doc.field.variable") };
  }
  const head = parts.length > 1 ? parts[0]! : "";
  const mine = doc?.template ? pack.templates.find((x) => x.name === doc.template) : undefined;
  const tpls = head && pack.templates.some((x) => x.name === head) ? pack.templates.filter((x) => x.name === head) : [...(mine ? [mine] : []), ...pack.templates.filter((x) => x !== mine)];
  if (parts.length > 2 || (head && head !== "self" && head !== "target" && !pack.templates.some((x) => x.name === head))) return null;
  const prefix = head === "target" ? t("doc.field.target") : "";
  for (const tpl of tpls) {
    const f = (tpl.fields ?? []).find((x) => x.name === last);
    if (f) return field(f, prefix);
    const d = (tpl.derived ?? []).find((x) => x.name === last);
    if (d) return { title: d.label ? `${word} — ${d.label}` : word, body: [prefix, t("doc.field.derived"), d.formula].filter(Boolean).join(" · ") };
  }
  if (!head) {
    const nf = (pack.formulas ?? []).find((x) => x.name === word);
    if (nf) return { title: word, body: `${t("doc.field.formula")} · ${nf.formula}` };
    if ((pack.tables ?? []).some((x) => x.name === word)) return { title: word, body: t("doc.field.table") };
  }
  return null;
}
