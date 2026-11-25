import { describe, expect, it } from "vitest";
import { toCode } from "./effectsCode";

describe("old bonus lists shown as code", () => {
  it("uses += and friends where it means the same", () => {
    expect(
      toCode([
        { description: "力量 +2", target: "str", formula: "str + 2", priority: null },
        { description: "让对手心生畏惧", target: null, formula: null, priority: null },
        { description: "", target: "move_speed", formula: "move_speed * 1.2", priority: 3 },
        { description: "", target: "hp_max", formula: "hp_max * 2 + 1", priority: null },
        { description: "", target: "per", formula: "self.per + 1 if self.dex > 2 else self.per", priority: null },
        { description: "", target: null, formula: null, priority: null },
      ]),
    ).toBe(
      "self.str += 2  # 力量 +2\n# 让对手心生畏惧\nself.move_speed *= 1.2\nself.hp_max = hp_max * 2 + 1\nself.per = self.per + 1 if self.dex > 2 else self.per",
    );
  });
});
