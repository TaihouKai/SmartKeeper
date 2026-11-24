import { describe, expect, it } from "vitest";
import { builtinDoc } from "./codeDocs";

describe("builtinDoc", () => {
  it("finds actions, functions, settings and constructor parameters", () => {
    expect(builtinDoc("target.damage", null, false)?.doc.sig).toBe("damage(amount)");
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
