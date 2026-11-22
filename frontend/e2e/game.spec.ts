import { expect, test, type Browser, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const SERVER = "http://127.0.0.1:8765";
const PASSWORD = "e2e-admin-password";
const SHOTS = process.env.SK_SHOTS;

async function shot(page: Page, name: string) {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });
}

/** 管理员只做准备工作（导入规则包、建局、发邀请、开局），之后不再介入。 */
async function setup(browser: Browser, players: number): Promise<{ gameId: string; invites: string[] }> {
  const ctx = await browser.newContext();
  const req = ctx.request;
  expect((await req.post(`${SERVER}/api/admin/login`, { data: { password: PASSWORD } })).ok()).toBeTruthy();
  const text = readFileSync(fileURLToPath(new URL("../../tests/fixtures/rulepack_single.json", import.meta.url)), "utf-8");
  const v = await (await req.post(`${SERVER}/api/admin/rulepacks/import`, { data: { text } })).json();
  const g = await (
    await req.post(`${SERVER}/api/admin/games`, {
      data: {
        name: "e2e", rulepack_id: v.pack_id, rulepack_version: v.version, map_id: "demo_shibuya", scenario: "demo",
        settings: { review_mode: false, web_search: false, kp_language: "zh" },
      },
    })
  ).json();
  const invites: string[] = [];
  for (let i = 0; i < players; i++) {
    const r = await (await req.post(`${SERVER}/api/admin/games/${g.id}/invites`, { data: { display_name: `Player${i + 1}` } })).json();
    invites.push(r.url);
  }
  return { gameId: g.id, invites };
}

async function startGame(browser: Browser, gameId: string) {
  const ctx = await browser.newContext();
  await ctx.request.post(`${SERVER}/api/admin/login`, { data: { password: PASSWORD } });
  const r = await ctx.request.patch(`${SERVER}/api/admin/games/${gameId}`, { data: { action: "start" } });
  expect(r.ok(), await r.text()).toBeTruthy();
}

async function createCharacter(page: Page, i: number) {
  await page.getByRole("button", { name: "Draw an identity" }).click();
  await expect(page.getByText("Identity").first()).toBeVisible();
  const form = page.locator(".sk-sheet-editor").first();
  await expect(form).toBeVisible();
  await form.getByLabel("Name", { exact: true }).fill(`Hero ${i}`);
  await form.getByLabel("appearance").fill(i % 2 ? "tall, grey coat" : "short, red scarf");
  await form.getByLabel("occupation").selectOption("reporter");
  await form.getByLabel("str").fill("50");
  await form.getByLabel("dex").fill("60");
  await form.getByLabel("per").fill("40");
  await expect(page.locator(".sk-preview")).toContainText("perception_radius");
  await page.getByRole("button", { name: "Submit character" }).click();
  await expect(page.getByText("Approved").first()).toBeVisible({ timeout: 20_000 });
}

async function act(page: Page, text: string) {
  const box = page.locator(".sk-box").first();
  await box.locator("textarea").fill(text);
  await box.getByRole("button", { name: "Parse" }).click();
  await expect(page.locator(".sk-echo")).toBeVisible({ timeout: 20_000 });
  await page.getByRole("button", { name: "Confirm" }).click();
  await expect(page.locator(".sk-echo")).toHaveCount(0);
}

test("three players create characters and play two rounds without the console", async ({ browser }) => {
  test.setTimeout(180_000);
  const { gameId, invites } = await setup(browser, 3);
  const pages: Page[] = [];
  for (const [i, url] of invites.entries()) {
    const ctx = await browser.newContext({ viewport: { width: 420, height: 860 }, locale: "en-US" });
    const page = await ctx.newPage();
    await page.goto(url);
    await expect(page).toHaveURL(/\/join$/);
    await createCharacter(page, i);
    pages.push(page);
  }
  await shot(pages[0]!, "join-approved");
  await startGame(browser, gameId);
  // 开场在后台进行（KP 写开场、起代号），等它完成
  for (const page of pages) {
    await expect(async () => {
      await page.goto(`${SERVER}/play`);
      await expect(page.locator(".sk-statusbar")).toContainText("Round 1", { timeout: 2_000 });
    }).toPass({ timeout: 60_000 });
  }
  for (const round of [1, 2]) {
    for (const [i, page] of pages.entries()) {
      await act(page, `Round ${round}: player ${i + 1} looks around the square.`);
    }
    for (const page of pages) {
      await expect(async () => {
        await page.reload();
        await expect(page.locator(".sk-statusbar")).toContainText(`Round ${round + 1}`, { timeout: 2_000 });
      }).toPass({ timeout: 60_000 });
      await expect(page.locator(".sk-event.feedback")).toHaveCount(round);
    }
  }
  await shot(pages[0]!, "play-kp");
  // 地图页：3D 地图和在场列表
  await pages[0]!.getByRole("button", { name: "Map" }).click();
  await expect(pages[0]!.locator(".maplibregl-canvas")).toBeVisible();
  await pages[0]!.waitForTimeout(2500);
  // 整页截图会改变视口，WebGL 画布在那一刻是空的；只截地图元素
  if (SHOTS) await pages[0]!.locator(".sk-map").screenshot({ path: `${SHOTS}/play-map.png` });
  await pages[1]!.getByRole("button", { name: "Sheet" }).click();
  await expect(pages[1]!.locator(".sk-card h3")).toContainText("Hero 1");
  await shot(pages[1]!, "play-sheet");
});

test("admin console login and panels render", async ({ page }) => {
  await page.goto(`${SERVER}/admin`);
  await page.getByLabel("Admin password").fill(PASSWORD);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page.getByRole("button", { name: "Games" })).toBeVisible();
  await page.getByRole("button", { name: "Rules" }).click();
  await expect(page.getByText("How far (in metres) this character notices others").first()).toBeVisible();
  // 新的空白规则包：引擎必需的推导值公式还是空的，不能保存
  await expect(page.getByText("can't save yet")).toBeVisible({ timeout: 10_000 });
  await expect(page.getByRole("button", { name: "Save as new version" })).toBeDisabled();
  await shot(page, "admin-rules");
  await page.getByRole("button", { name: "Materials" }).click();
  await expect(page.getByText("demo").first()).toBeVisible();
  // 选中上一个测试建的局，看世界状态和 LLM 调用面板
  await page.getByRole("button", { name: "Games" }).click();
  await page.locator(".sk-chip", { hasText: "e2e" }).first().click();
  await page.getByRole("button", { name: "World state" }).click();
  await expect(page.locator("pre.sk-code").first()).toContainText("game_minutes");
  await page.getByRole("button", { name: "LLM calls" }).click();
  await expect(page.getByText("adjudicate").first()).toBeVisible();
  await page.getByText("adjudicate").first().click();
  await expect(page.getByText("System prompt")).toBeVisible();
  await shot(page, "admin-llm");
});
