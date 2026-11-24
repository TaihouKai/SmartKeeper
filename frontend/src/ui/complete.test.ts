import { describe, expect, it } from "vitest";
import { suggest } from "./complete";

const NAMES = ["hp", "hp_max", "master.hp", "master.template", "master.fireball", "master.fireball.level", "master.skills.cost", "max", "target.hp"];

describe("suggest", () => {
  it("lists every next segment after a dot, not just the first few", () => {
    const got = suggest(NAMES, "master.");
    expect(got.map((s) => s.label)).toEqual(["fireball", "hp", "skills", "template"]);
    expect(got.find((s) => s.label === "fireball")).toEqual({ insert: "master.fireball", label: "fireball", more: true });
    // 只能接着点的（分组）选中时带上点
    expect(got.find((s) => s.label === "skills")?.insert).toBe("master.skills.");
  });

  it("filters by what is typed after the last dot", () => {
    expect(suggest(NAMES, "master.f").map((s) => s.insert)).toEqual(["master.fireball"]);
    expect(suggest(NAMES, "master.fireball.").map((s) => s.insert)).toEqual(["master.fireball.level"]);
  });

  it("top level shows one segment per name and hides what is already typed", () => {
    expect(suggest(NAMES, "m").map((s) => s.label)).toEqual(["master", "max"]);
    expect(suggest(NAMES, "hp").map((s) => s.label)).toEqual(["hp_max"]);
    expect(suggest(NAMES, "")).toEqual([]);
  });
});
