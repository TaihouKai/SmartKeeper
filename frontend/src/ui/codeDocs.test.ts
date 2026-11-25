import { describe, expect, it } from "vitest";
import { builtinDoc } from "./codeDocs";
import { setDocsCatalog, type DocEntry } from "./docs";

// 目录平时由后端从公式语言的定义生成（/api/lobby/docs）；这里放几条一样的
setDocsCatalog(([
  { name: "damage", category: "verb", sig: 'damage(amount, kind="")', desc: "doc.verb.damage", params: [["amount", "doc.p.amount_dice"], ["kind", "doc.p.damage_kind"]] },
  { name: "add", category: "verb", sig: "add(field, amount, minutes=None)", desc: "doc.verb.add", params: [["field", "doc.p.runtime_field"], ["amount", "doc.p.amount_dice"], ["minutes", "doc.p.timed_minutes"]] },
  { name: "max", category: "function", sig: "max(a, b, …)", desc: "fh.fn.max", params: [] },
  { name: "range", category: "config", sig: "range = …", desc: "config.c.range", params: [] },
  { name: "placement", category: "config", sig: "placement = …", desc: "config.c.placement", params: [] },
  { name: "placement", category: "shape", sig: "placement(radius, perceive=1, charges=None, duration=None, notify=True, building=False)", desc: "doc.placement", params: [["radius", "doc.p.placement_radius"], ["notify", "doc.p.notify"]] },
] as Omit<DocEntry, "values" | "example">[]).map((d) => ({ ...d, values: [], example: "" })));

describe("builtinDoc", () => {
  it("finds actions, functions, settings and constructor parameters", () => {
    expect(builtinDoc("target.damage", null, false)?.doc.sig).toBe('damage(amount, kind="")');
    expect(builtinDoc("self.add", null, false)?.doc.params?.map(([p]) => p)).toEqual(["field", "amount", "minutes"]);
    expect(builtinDoc("max", null, false)?.doc.desc).toBe("fh.fn.max");
    expect(builtinDoc("range", null, true)?.doc.desc).toBe("config.c.range");
    // placement(…, notify=True) 里的 notify：构造的参数
    const p = builtinDoc("notify", "placement", true);
    expect(p?.param).toBe("notify");
    expect(p?.doc.sig.startsWith("placement(")).toBe(true);
    // 设置项 placement 和构造 placement(…) 不一样
    expect(builtinDoc("placement", null, true)?.doc.desc).toBe("config.c.placement");
    expect(builtinDoc("placement", null, false)?.doc.desc).toBe("doc.placement");
    expect(builtinDoc("this.level", null, false)).toBeNull();
  });
});
