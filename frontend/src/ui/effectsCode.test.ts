import { describe, expect, it } from "vitest";
import { fromCode, parseCode, toCode } from "./effectsCode";

describe("effects as code", () => {
  it("round-trips assignments, notes and note-only lines", () => {
    const effects = [
      { description: "力量 +2", target: "str", formula: "self.str + 2", priority: null },
      { description: "让对手心生畏惧", target: null, formula: null, priority: null },
      { description: "", target: "move_speed", formula: "move_speed * 1.2", priority: 3 },
    ];
    const text = toCode(effects);
    expect(text).toBe("self.str = self.str + 2  # 力量 +2\n# 让对手心生畏惧\nself.move_speed = move_speed * 1.2");
    expect(fromCode(text, effects)).toEqual(effects);
  });

  it("reports lines that are not assignments and keeps # inside quotes", () => {
    const parsed = parseCode('self.str = 1\noops\nself.x = 2 if self.job == "#1" else 3');
    expect(parsed[1]).toEqual({ line: 2, error: "effects.bad_line" });
    expect(parsed[2]).toMatchObject({ effect: { target: "x", formula: '2 if self.job == "#1" else 3' } });
    expect(parseCode("self.a == 1")[0]).toEqual({ line: 1, error: "effects.bad_line" });
  });
});

describe("blank leftovers", () => {
  it("are hidden and dropped instead of bouncing back and forth", () => {
    const blank = [{ description: "", target: null, formula: null, priority: null }];
    expect(toCode(blank)).toBe("");
    expect(fromCode(toCode(blank), blank)).toEqual([]);
  });
});
