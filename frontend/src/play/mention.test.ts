import { describe, expect, it } from "vitest";
import { filterMentions, insertMention, mentionQuery } from "./mention";

describe("mentionQuery", () => {
  it("finds the @word being typed", () => {
    expect(mentionQuery("去 @教", 4)).toEqual({ start: 2, query: "教" });
    expect(mentionQuery("@", 1)).toEqual({ start: 0, query: "" });
  });
  it("works right after Chinese text, with no space", () => {
    expect(mentionQuery("去@教", 3)).toEqual({ start: 1, query: "教" });
    expect(mentionQuery("我和@", 3)).toEqual({ start: 2, query: "" });
    expect(mentionQuery("（@Ri", 4)).toEqual({ start: 1, query: "Ri" });
    expect(mentionQuery("去＠教", 3)).toEqual({ start: 1, query: "教" });
  });
  it("ignores mail-like @ and finished mentions", () => {
    expect(mentionQuery("a@b", 3)).toBeNull();
    expect(mentionQuery("@[教会](feature:x) ", 17)).toBeNull();
    expect(mentionQuery("@教会 去", 5)).toBeNull();
  });
});

describe("filterMentions", () => {
  it("keeps matches, prefix matches first", () => {
    const list = [{ label: "白色的骑士" }, { label: "骑士团" }, { label: "教会" }];
    expect(filterMentions(list, "骑士").map((x) => x.label)).toEqual(["骑士团", "白色的骑士"]);
    expect(filterMentions(list, "").length).toBe(3);
  });
});

describe("insertMention", () => {
  it("replaces the @word and places the caret after it", () => {
    expect(insertMention("去 @教 登记", 2, 4, "@[教会](feature:b1)")).toEqual({ text: "去 @[教会](feature:b1) 登记", caret: 20 });
  });
});
