import zh from "./zh.json";
import en from "./en.json";
import { translate } from "./index";

/** 代码里用模板字符串拼出来的键：每一族的每个取值在两种语言里都要有。 */
const DYNAMIC: Record<string, string[]> = {
  "join.status": ["none", "submitted", "approved", "rejected"],
  "status.phase": ["collecting", "adjudicating", "review", "published"],
  "status.me": ["act", "submitted", "busy", "idle"],
  "rules.default_label": ["appearance", "can_fly", "hp", "mp", "sp", "san", "shield", "perception_radius", "concealment", "move_speed", "fly_multiplier", "fly_speed", "hear_multiplier", "hear_distance"],
  "games.status": ["setup", "characters", "running", "ended"],
  shape: ["capsule", "box", "sphere", "cone", "length", "width", "height", "radius", "angle"],
  "sheet.source": ["feedback", "admin", "engine", "opening"],
};

describe("dynamic translation keys", () => {
  for (const [prefix, values] of Object.entries(DYNAMIC)) {
    for (const v of values) {
      it(`${prefix}.${v}`, () => {
        for (const lang of ["zh", "en"] as const) {
          expect(translate(lang, `${prefix}.${v}`)).not.toBe(`${prefix}.${v}`);
        }
      });
    }
  }
  it("tables are non-empty", () => {
    expect(Object.keys(zh).length).toBeGreaterThan(5);
    expect(Object.keys(en).length).toBe(Object.keys(zh).length);
  });
});
