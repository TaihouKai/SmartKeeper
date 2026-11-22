import { expect, test } from "@playwright/test";

test("map demo renders buildings and picks things", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/demo/index.html");
  await expect(page.locator(".maplibregl-canvas")).toBeVisible();
  await expect(page.locator(".sk-marker")).toHaveCount(4);
  await expect(page.locator(".sk-map-attribution")).toContainText("OpenStreetMap");
  await page.waitForTimeout(2500);
  if (process.env.SK_SHOT) await page.screenshot({ path: process.env.SK_SHOT });
  // 点实体
  await page.locator(".sk-marker", { hasText: "Grey coat" }).click();
  await expect(page.getByTestId("pick-info")).toContainText("Grey coat");
  // 点地图中心附近：要么点到建筑，要么点到地面
  const box = await page.locator(".maplibregl-canvas").boundingBox();
  if (!box) throw new Error("no canvas");
  await page.mouse.click(box.x + box.width * 0.5, box.y + box.height * 0.8);
  await expect(page.getByTestId("pick-info")).not.toContainText("Grey coat");
  expect(errors).toEqual([]);
});
