import { translate } from "./index";

describe("translate", () => {
  it("renders params", () => {
    expect(translate("en", "app.title")).toBe("SmartKeeper");
  });
  it("falls back to the key", () => {
    expect(translate("zh", "missing.key")).toBe("missing.key");
  });
});
