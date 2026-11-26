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

/** 管理员手动修改：把各玩家的第一个实体放到指定坐标（米）。 */
async function placePlayers(browser: Browser, gameId: string, where: Record<string, [number, number]>) {
  const ctx = await browser.newContext();
  const req = ctx.request;
  await req.post(`${SERVER}/api/admin/login`, { data: { password: PASSWORD } });
  const detail = await (await req.get(`${SERVER}/api/admin/games/${gameId}`)).json();
  const state = await (await req.get(`${SERVER}/api/admin/games/${gameId}/state`)).json();
  const ops: unknown[] = [];
  for (const p of detail.players as { id: string; display_name: string }[]) {
    const xy = where[p.display_name];
    const eid = (state.controls[p.id] as string[] | undefined)?.[0];
    if (!xy || !eid) continue;
    ops.push({ op: "replace", path: `/entities/${eid}/pos`, value: { x: xy[0], y: xy[1], z: 0 } });
    ops.push({ op: "replace", path: `/entities/${eid}/inside`, value: null });
  }
  const r = await req.patch(`${SERVER}/api/admin/games/${gameId}/state`, { data: { ops, note: "e2e" } });
  expect(r.ok(), await r.text()).toBeTruthy();
  await ctx.close();
}

async function createCharacter(page: Page, i: number) {
  await page.getByRole("button", { name: "Draw an identity" }).click();
  await expect(page.getByText("Identity").first()).toBeVisible();
  // 先看剧本背景、选角色：从角色库里挑，或者新建（第一个人的时候库是空的）
  await expect(page.getByText("Scenario background")).toBeVisible();
  await page.getByRole("button", { name: "New character" }).click();
  const form = page.locator(".cf").first();
  await expect(form).toBeVisible();
  // 身份一节：名字、外观、职业
  await form.getByLabel("Name", { exact: true }).fill(`Hero ${i}`);
  await form.getByLabel("appearance").fill(i % 2 ? "tall, grey coat" : "short, red scarf");
  await form.getByLabel("occupation").selectOption("reporter");
  // 数值一节
  await form.locator(".cf-nav").getByRole("button", { name: /Numbers/ }).click();
  await form.getByLabel("str").fill("50");
  await form.getByLabel("dex").fill("60");
  await form.getByLabel("per").fill("40");
  await expect(page.locator(".cf-side")).toContainText("perception_radius");
  await expect(page.locator(".cf-footer")).toContainText("All filled in");
  await page.getByRole("button", { name: "Submit character" }).click();
  await expect(page.getByText("Approved").first()).toBeVisible({ timeout: 20_000 });
}

async function act(page: Page, text: string) {
  // 聊天面板的 KP 会话，“行动”模式：这里只写补充说明（交给 KP 解析），不点技能
  const box = page.locator(".pl-composer");
  await box.locator("textarea").fill(text);
  await box.getByRole("button", { name: "Check time & submit" }).click();
  await expect(page.locator(".sk-echo")).toBeVisible({ timeout: 20_000 });
  await expect(page.locator(".sk-echo")).toContainText("Estimated time 1m 0s");
  await shot(page, "play-echo");
  await page.getByRole("button", { name: "Confirm" }).click();
  await expect(page.locator(".sk-echo")).toHaveCount(0);
}

test("three players create characters and play two rounds without the console", async ({ browser }) => {
  test.setTimeout(300_000);
  const { gameId, invites } = await setup(browser, 3);
  const pages: Page[] = [];
  for (const [i, url] of invites.entries()) {
    const ctx = await browser.newContext({ viewport: { width: 420, height: 860 }, locale: "en-US" });
    const page = await ctx.newPage();
    await page.goto(url);
    await expect(page).toHaveURL(new RegExp(`/g/${gameId}$`)); // 邀请链接带到这一局自己的网址
    await createCharacter(page, i);
    pages.push(page);
  }
  await shot(pages[0]!, "join-approved");
  await startGame(browser, gameId);
  // 开场在后台进行（KP 写开场、起代号），等它完成
  for (const page of pages) {
    await expect(async () => {
      await page.goto(`${SERVER}/play`);
      await expect(page.locator(".sk-statusbar")).toContainText("Your move", { timeout: 2_000 });
    }).toPass({ timeout: 60_000 });
  }
  for (const round of [1, 2]) {
    for (const [i, page] of pages.entries()) {
      await act(page, `Round ${round}: player ${i + 1} looks around the square.`);
    }
    for (const page of pages) {
      await expect(async () => {
        await page.reload();
        await expect(page.locator(".pl-msg.kp")).toHaveCount(round, { timeout: 2_000 });
      }).toPass({ timeout: 60_000 });
      // 玩家看不到回合数，只看到自己的时间和状态
      await expect(page.locator(".sk-statusbar")).toContainText("Your move");
      await expect(page.locator(".sk-statusbar")).not.toContainText("Round");
    }
  }
  await shot(pages[0]!, "play-kp");
  // 对话模式：玩家 1 在地图页向身边的 NPC 发起对话，说一句，等对方（脚本化 KP 扮演）回话，再结束
  // 身份是随机抽的，开场位置也就不同：用管理员手动修改把玩家 1 放到卖花老人（20, -30）身边，其他人放远
  await placePlayers(browser, gameId, { Player1: [20, -34], Player2: [-90, -90], Player3: [-90, -80] });
  const a = pages[0]!;
  await a.reload();
  // 地图下面“身边的人”里点“交谈”：聊天面板切到这场对话
  await a.locator(".pl-people li").first().getByRole("button", { name: "Talk", exact: true }).click();
  // 等聊天面板换到这场对话（换之前看到的还是 KP 会话的输入框）
  await expect(a.locator(".pl-conv-head")).toContainText("Talk ·", { timeout: 10_000 });
  await a.locator(".pl-composer textarea").fill("Did you see the package?");
  await a.getByRole("button", { name: "Say", exact: true }).click();
  await expect(a.locator(".pl-msgs")).toContainText("Did you see the package?");
  // NPC 的回话按长度延迟出现（模拟打字）
  await expect(a.locator(".pl-msgs .pl-msg:not(.mine)")).toHaveCount(1, { timeout: 30_000 });
  await shot(a, "play-talk");
  await a.getByRole("button", { name: "End conversation" }).click();
  await expect(a.locator(".pl-composer")).toContainText("The conversation is over.", { timeout: 10_000 });
  // 地图和聊天在同一屏
  await expect(pages[0]!.locator(".maplibregl-canvas")).toBeVisible();
  await pages[0]!.waitForTimeout(2500);
  // 整页截图会改变视口，WebGL 画布在那一刻是空的；只截地图元素
  if (SHOTS) await pages[0]!.locator(".sk-map").screenshot({ path: `${SHOTS}/play-map.png` });
  // 结盟：玩家 1 和玩家 2 站到一起（远离 NPC），1 提议，2 同意，双方都显示盟友
  await placePlayers(browser, gameId, { Player1: [20, -34], Player2: [22, -34], Player3: [-90, -90] });
  for (const p of [pages[0]!, pages[1]!]) {
    await p.reload();
  }
  // 身边是玩家 2 和卖花老人（NPC），代号看不出谁是谁：都提一次。对着 NPC 的提议一直挂着，没人回应
  const near = a.locator(".pl-people li", { has: a.getByRole("button", { name: "Talk", exact: true }) });
  for (let i = 0; i < (await near.count()); i++) {
    await near.nth(i).getByRole("button", { name: "Propose alliance" }).click();
    await a.waitForTimeout(300);
  }
  await expect(a.locator(".pl-alliance")).toContainText("Waiting for", { timeout: 10_000 });
  const b = pages[1]!;
  await expect(async () => {
    await b.reload();
    await expect(b.locator(".pl-alliance")).toContainText("proposes an alliance", { timeout: 2_000 });
  }).toPass({ timeout: 20_000 });
  await b.locator(".pl-alliance").getByRole("button", { name: "Accept" }).click();
  await expect(b.locator(".pl-alliance")).toContainText("Ally:", { timeout: 10_000 });
  await a.reload();
  await expect(a.locator(".pl-alliance")).toContainText("Ally:", { timeout: 10_000 });
  await shot(a, "play-alliance");
  await pages[1]!.getByRole("button", { name: "Sheet" }).click();
  await expect(pages[1]!.locator(".pl-sheet-card h3")).toContainText("Hero 1");
  await shot(pages[1]!, "play-sheet");
});

test("admin console login and panels render", async ({ page }) => {
  await page.goto(`${SERVER}/admin`);
  await page.getByLabel("Admin password").fill(PASSWORD);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page.getByRole("button", { name: "Games" })).toBeVisible();
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole("button", { name: "Rules" }).click();
  // 规则工作台：左边目录，中间一节，右边 IDE
  await page.locator(".wb-node", { hasText: "Derived values" }).first().click();
  await expect(page.getByText("How far (in metres) this character notices others").first()).toBeVisible();
  // 新的空白规则包：引擎必需的推导值公式还是空的，不能保存
  await expect(page.locator(".wb-chip.bad")).toBeVisible({ timeout: 10_000 });
  await expect(page.getByRole("button", { name: "Save as new version" })).toBeDisabled();
  // 公式框右边的 ⤢ 在 IDE 里打开这一段
  await page.locator(".sk-expand").first().click();
  await expect(page.locator(".wb-ide-tab")).toHaveCount(1);
  await expect(page.locator(".wb-cm .cm-content")).toBeVisible();
  // 没写完也能存草稿；草稿出现在规则包列表里
  await page.locator(".wb-node", { hasText: "World" }).first().click();
  await page.getByLabel("Name", { exact: true }).first().fill("Unfinished e2e pack");
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page.locator(".wb-saved")).toContainText("Saved");
  await page.locator(".wb-pack").click();
  await expect(page.locator(".wb-pop option", { hasText: "Draft" }).first()).toBeAttached();
  await page.keyboard.press("Escape");
  // 公式速查在 IDE 的工具里
  await page.locator(".wb-ide-tooltabs button", { hasText: "Reference" }).click();
  await expect(page.getByText("Roll 4d6 and keep the highest 3")).toBeVisible();
  await shot(page, "admin-rules");
  await page.getByRole("button", { name: "Materials" }).click();
  await expect(page.getByText("demo").first()).toBeVisible();
  // 选中上一个测试建的局，看世界状态和 LLM 调用面板
  await page.getByRole("button", { name: "Games" }).click();
  await page.locator(".sk-chip", { hasText: "e2e" }).first().click();
  await page.getByRole("button", { name: "World state" }).click();
  await expect(page.locator("pre.sk-code").first()).toContainText("game_seconds");
  await page.getByRole("button", { name: "LLM calls" }).click();
  await expect(page.getByText("adjudicate").first()).toBeVisible();
  await page.getByText("adjudicate").first().click();
  await expect(page.getByText("System prompt")).toBeVisible();
  await shot(page, "admin-llm");
});
