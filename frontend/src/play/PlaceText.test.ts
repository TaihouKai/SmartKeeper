import { describe, expect, it } from "vitest";
import { splitPlaces } from "./PlaceText";

const PLACES = [
  { id: "place_1", name: "教会" },
  { id: "place_2", name: "宫下公园" },
];

describe("splitPlaces", () => {
  it("turns engine links into places and features", () => {
    expect(splitPlaces("去[教会](place:place_1)登记，路过[Shibuya 109](feature:w12)。", [])).toEqual([
      "去",
      { kind: "place", id: "place_1", name: "教会" },
      "登记，路过",
      { kind: "feature", id: "w12", name: "Shibuya 109" },
      "。",
    ]);
  });

  it("links known place names in plain text, longest first", () => {
    const out = splitPlaces("午夜前到宫下公园旁的教会登记", [...PLACES, { id: "place_3", name: "宫下公园旁的教会" }]);
    expect(out).toEqual(["午夜前到", { kind: "place", id: "place_3", name: "宫下公园旁的教会" }, "登记"]);
  });

  it("does not link inside an engine link twice", () => {
    expect(splitPlaces("[教会](place:place_1)", PLACES)).toEqual([{ kind: "place", id: "place_1", name: "教会" }]);
  });

  it("leaves text without places alone", () => {
    expect(splitPlaces("什么都没有", PLACES)).toEqual(["什么都没有"]);
  });
});
