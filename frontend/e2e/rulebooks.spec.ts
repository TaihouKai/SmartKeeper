import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

// 页面和接口都走测试用的后端（它带着构建好的前端）
const SERVER = "http://127.0.0.1:8765";

type Pack = { pack: { world: { name: string }; samples: { template: string; sheet: Record<string, unknown> }[] } };

/** 规则书总览：和对局列表分开；不进任何一局就能在规则书下新建、修改、删除角色。 */
test("rulebooks: make, change and delete a character without joining a game", async ({ browser }) => {
  const text = readFileSync(fileURLToPath(new URL("../../tests/fixtures/rulepack_single.json", import.meta.url)), "utf-8");
  const parsed = JSON.parse(text) as Pack;
  const ctx = await browser.newContext({ locale: "en-US" });
  const page = await ctx.newPage();
  // 前面的测试已经导入过这套规则书时直接用（管理员登录有限速）；没有才导入
  const books = (await (await page.request.get(`${SERVER}/api/books`)).json()) as { id: string; world_name: string }[];
  let book = books.find((b) => b.world_name === parsed.pack.world.name)?.id;
  if (!book) {
    const admin = await browser.newContext();
    await admin.request.post(`${SERVER}/api/admin/login`, { data: { password: "e2e-admin-password" } });
    book = (await (await admin.request.post(`${SERVER}/api/admin/rulepacks/import`, { data: { text } })).json()).pack_id as string;
  }

  await page.goto(`${SERVER}/`);
  await page.locator(".bk-nav").getByRole("link", { name: "Rulebooks" }).click();
  await expect(page).toHaveURL(/\/books$/);
  await page.goto(`${SERVER}/books/${book}`);
  await expect(page.locator(".bk-columns h2")).toHaveText(["Scenarios", "Characters"]);

  // 新建：把示例卡放进浏览器暂存（照着填完整张卡太长），存进角色库
  const sheets = parsed.pack.samples.slice(0, 1).map((s) => ({ template: s.template, sheet: { groups: {}, preset_fields: {}, ...s.sheet } }));
  const key = `sk.bookDraft.${book}.new`;
  const value = JSON.stringify({ sheets, savedAt: new Date().toISOString() });
  await page.evaluate(({ k, v }) => window.localStorage.setItem(k, v), { k: key, v: value });
  await page.goto(`${SERVER}/books/${book}/characters/new`);
  const box = page.locator(".lib-box");
  await box.getByPlaceholder("Your name (shown to others)").fill("Tester");
  await box.getByPlaceholder("Empty: the sheets' names").fill("Sample hero");
  await box.locator("textarea").fill("first");
  await box.locator('input[type="password"]').fill("pw");
  await page.locator(".cf-footer").getByRole("button", { name: "Save to the library now" }).click();
  await expect(page).toHaveURL(/\/characters\/ch_/);

  // 再改再存：还是同一个角色
  await box.locator("textarea").fill("second");
  await page.locator(".cf-footer").getByRole("button", { name: "Save back to the library now" }).click();
  const mine = async () => {
    const listed = await (await page.request.get(`${SERVER}/api/books/${book}`)).json();
    return (listed.character_list as { name: string; summary: string; locked: boolean }[]).filter((c) => c.name === "Sample hero").map((c) => [c.summary, c.locked]);
  };
  await expect.poll(mine).toEqual([["second", true]]);

  // 建卡助手：从条目编辑器打开，问一句，应用它给的修改（测试用的是离线的假助手，不调用模型）
  await page.locator(".cf-nav").getByRole("button", { name: /Skills/ }).click();
  await page.locator(".cf-item", { hasText: "first aid" }).getByRole("button", { name: "Edit" }).click();
  await page.locator(".cf-drawer").getByRole("button", { name: /Ask Copilot/ }).click();
  const panel = page.locator(".cp-panel");
  await expect(panel).toContainText("first aid");
  await panel.locator("textarea").fill("make it better");
  await panel.getByRole("button", { name: "Send" }).click();
  await expect(panel.locator(".cp-a")).toContainText("make it better");
  await panel.getByRole("button", { name: "Apply" }).click();
  await expect(panel).toContainText("Applied");
  await panel.getByRole("button", { name: "Close" }).click();
  await expect(page.locator(".cf-drawer textarea").first()).toHaveValue(/make it better/);
  await page.locator(".cf-drawer").getByRole("button", { name: "Done" }).click();

  // 删除要密码
  await page.goto(`${SERVER}/books/${book}`);
  const row = page.locator(".bk-list li", { hasText: "Sample hero" });
  await row.getByRole("button", { name: "Delete" }).click();
  await row.locator('input[type="password"]').fill("pw");
  await row.locator(".bk-confirm").getByRole("button", { name: "Delete" }).click();
  await expect(page.locator(".bk-list li", { hasText: "Sample hero" })).toHaveCount(0);
});
