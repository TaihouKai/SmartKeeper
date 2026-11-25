import { describe, expect, it } from "vitest";
import { headings, section, toHtml } from "./markdown";

const BOOK = "# A\n\nintro\n\n## **B**\n\nbody of b\n\n### C\n\nsub\n\n## D\n\nd";

describe("rulebook sections", () => {
  it("cuts a section up to the next heading of the same level", () => {
    expect(section(BOOK, "B")).toBe("body of b\n\n### C\n\nsub");
    expect(section(BOOK, "D")).toBe("d");
    expect(section(BOOK, "Z")).toBeNull();
  });
  it("lists headings with anchors and links [[refs]]", () => {
    expect(headings(BOOK).map((h) => h.title)).toEqual(["A", "B", "C", "D"]);
    const html = toHtml("see [[B]]", "/rulebook");
    expect(html).toContain('href="/rulebook#h-B"');
    expect(toHtml("## **B**")).toContain('id="h-B"');
    expect(toHtml("<img src=x onerror=alert(1)>")).not.toContain("onerror");
  });
});
