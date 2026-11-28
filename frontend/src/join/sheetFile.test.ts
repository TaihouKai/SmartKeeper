import { describe, expect, it } from "vitest";
import { SheetFileError, readSheetFile, sheetFileName, sheetFileText } from "./sheetFile";

const entities = [
  { template: "leader", min: 1, max: 1 },
  { template: "companion", min: 1, max: 2 },
];
const card = (template: string, name: string) => ({ template, sheet: { name, fields: { bio: "x" }, groups: {} } });

describe("character sheet file", () => {
  it("reads back what it wrote", () => {
    const sheets = [card("leader", "A"), card("companion", "B")];
    const text = sheetFileText(sheets);
    expect(JSON.parse(text).kind).toBe("smartkeeper.character");
    expect(readSheetFile(text, entities)).toEqual({ sheets, skipped: 0 });
  });

  it("accepts a bare list, keeps the rulebook's order, drops foreign and surplus sheets, fills missing ones", () => {
    const r = readSheetFile(JSON.stringify([card("companion", "S1"), card("dragon", "D"), card("companion", "S2"), card("companion", "S3")]), entities);
    expect(r.skipped).toBe(2);
    expect(r.sheets.map((x) => [x.template, x.sheet.name])).toEqual([
      ["leader", ""],
      ["companion", "S1"],
      ["companion", "S2"],
    ]);
  });

  it("refuses files that are not sheets, and sheets for another rulebook", () => {
    expect(() => readSheetFile("not json", entities)).toThrow(SheetFileError);
    expect(() => readSheetFile(JSON.stringify({ hello: 1 }), entities)).toThrow(new SheetFileError("bad"));
    expect(() => readSheetFile(JSON.stringify([card("dragon", "D")]), entities)).toThrow(new SheetFileError("none"));
  });

  it("names the file after the characters", () => {
    expect(sheetFileName(["A", " ", "B/C"])).toBe("A_BC.json");
    expect(sheetFileName([])).toBe("character.json");
  });
});
