import { FUNCTION_SIGNATURES } from "./FormulaHelp";

/** 悬停提示的一条：签名、说明、各参数（名字、说明）。文字都是翻译键，显示时再翻译。 */
export type Doc = { sig: string; desc: string; params?: [string, string][] };

/** 技能脚本的动作（self. / target. 后面的名字）。和后端 lang/script.py 的 VERBS 对应。 */
const VERBS: Record<string, Doc> = {
  damage: { sig: "damage(amount)", desc: "doc.verb.damage", params: [["amount", "doc.p.amount_dice"]] },
  add: {
    sig: "add(field, amount, minutes=None)",
    desc: "doc.verb.add",
    params: [
      ["field", "doc.p.runtime_field"],
      ["amount", "doc.p.amount_dice"],
      ["minutes", "doc.p.timed_minutes"],
    ],
  },
  sub: { sig: "sub(field, amount)", desc: "doc.verb.sub", params: [["field", "doc.p.runtime_field"], ["amount", "doc.p.amount_dice"]] },
  set: { sig: "set(field, amount)", desc: "doc.verb.set", params: [["field", "doc.p.runtime_field"], ["amount", "doc.p.amount_dice"]] },
  negate: { sig: "negate()", desc: "doc.verb.negate" },
  modify: {
    sig: "modify(derived, formula, minutes)",
    desc: "doc.verb.modify",
    params: [
      ["derived", "doc.p.derived"],
      ["formula", "doc.p.modify_formula"],
      ["minutes", "doc.p.minutes"],
    ],
  },
};

/** 技能设置的构造：参数和说明。和后端 rules/skillconfig.py 的 SHAPES、PLACEMENT_ARGS 对应。 */
const CALLS: Record<string, Doc> = {
  sphere: { sig: "sphere(radius)", desc: "doc.shape.sphere", params: [["radius", "doc.p.radius_m"]] },
  cone: { sig: "cone(length, angle)", desc: "doc.shape.cone", params: [["length", "doc.p.length_m"], ["angle", "doc.p.angle"]] },
  capsule: { sig: "capsule(length, width)", desc: "doc.shape.capsule", params: [["length", "doc.p.length_m"], ["width", "doc.p.width_m"]] },
  box: { sig: "box(length, width, height)", desc: "doc.shape.box", params: [["length", "doc.p.length_m"], ["width", "doc.p.width_m"], ["height", "doc.p.height_m"]] },
  placement: {
    sig: "placement(radius, perceive=1, charges=None, duration=None, notify=True)",
    desc: "doc.placement",
    params: [
      ["radius", "doc.p.placement_radius"],
      ["perceive", "doc.p.perceive"],
      ["charges", "doc.p.charges"],
      ["duration", "doc.p.duration"],
      ["notify", "doc.p.notify"],
    ],
  },
};

/** 技能设置的项。 */
const SETTINGS: Record<string, Doc> = Object.fromEntries(
  ["target", "range", "visible", "requires", "noise", "cast_time", "cooldown", "check", "difficulty", "reactions", "shape", "placement"].map((k) => [k, { sig: `${k} = …`, desc: `config.c.${k}` }]),
);

const KEYWORDS: Record<string, Doc> = {
  if: { sig: "if cond:  /  a if cond else b", desc: "doc.kw.if" },
  elif: { sig: "elif cond:", desc: "fh.s.else" },
  else: { sig: "else:", desc: "fh.s.else" },
  and: { sig: "a and b", desc: "doc.kw.and" },
  or: { sig: "a or b", desc: "doc.kw.or" },
  not: { sig: "not a", desc: "doc.kw.not" },
  None: { sig: "None", desc: "doc.kw.none" },
  pass: { sig: "pass", desc: "doc.kw.pass" },
  self: { sig: "self", desc: "doc.kw.self" },
  target: { sig: "target", desc: "doc.kw.target" },
  this: { sig: "this", desc: "doc.kw.this" },
  result: { sig: 'result == "critical_success"', desc: "doc.kw.result" },
  reacting: { sig: "if reacting:", desc: "doc.kw.reacting" },
};

/** 检定的代码：各项和结果条件里能用的变量（只在编辑检定时用）。 */
export const CHECK_DOCS: Record<string, Doc> = Object.fromEntries([
  ...["label", "dice", "target", "critical_success", "critical_failure", "success", "opposed_by"].map((k) => [k, { sig: `${k} = …`, desc: `check.c.${k}` }]),
  ...["roll", "natural", "difficulty", "opp_roll", "opp_target"].map((k) => [k, { sig: k, desc: `check.v.${k}` }]),
]);

const FUNCS: Record<string, Doc> = Object.fromEntries(FUNCTION_SIGNATURES.map(([name, sig]) => [name, { sig, desc: `fh.fn.${name}` }]));

/**
 * 光标下这个名字的说明。word 是带点的整个名字（self.add），call 是它所在的调用（写在 placement( … ) 里的参数名时是 placement），
 * keyword 表示它后面紧跟着单个 =（是参数名或设置项的名字）。
 */
export function builtinDoc(word: string, call: string | null, keyword: boolean): { doc: Doc; param?: string } | null {
  if (keyword && call && CALLS[call]?.params?.some(([p]) => p === word)) return { doc: CALLS[call]!, param: word };
  const [head, ...rest] = word.split(".");
  if ((head === "self" || head === "target") && rest.length === 1 && VERBS[rest[0]!]) return { doc: VERBS[rest[0]!]! };
  if (rest.length) return null;
  if (keyword && SETTINGS[word]) return { doc: SETTINGS[word]! };
  const d = CALLS[word] ?? FUNCS[word] ?? KEYWORDS[word] ?? SETTINGS[word];
  return d ? { doc: d } : null;
}
