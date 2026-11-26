import { describe, expect, it } from "vitest";
import { numberOptions, showNumber, withUnit } from "./choices";

describe("number choices", () => {
  it("labels, single numbers and ranges", () => {
    const fate = ["E=1", "D=2", "C=3", "B=4", "A=5", "EX=10"];
    expect(numberOptions(fate).map((o) => o.label)).toEqual(["E", "D", "C", "B", "A", "EX"]);
    expect(showNumber(fate, 10)).toBe("EX");
    expect(numberOptions(["1~5", "10"]).map((o) => o.value)).toEqual([1, 2, 3, 4, 5, 10]);
    expect(numberOptions(["1~3", "EX=3"]).find((o) => o.value === 3)?.label).toBe("EX");
    expect(showNumber(undefined, 4)).toBe("4");
  });
});

describe("withUnit", () => {
  it("adds the pack's unit and rounds", () => {
    expect(withUnit(110, "m/min")).toBe("110 m/min");
    expect(withUnit(1.23456, null)).toBe("1.23");
  });
});
