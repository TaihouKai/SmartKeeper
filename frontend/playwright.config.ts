import { join } from "node:path";
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:5179",
    viewport: { width: 1000, height: 800 },
    // 无头模式下用软件 WebGL（SwiftShader），地图才能渲染
    launchOptions: { args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] },
  },
  webServer: [
    {
      command: "npx vite --port 5179 --strictPort --host 127.0.0.1",
      url: "http://127.0.0.1:5179/demo/index.html",
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      // 后端：新的临时数据库、脚本化的假 KP；静态文件来自 frontend/dist（先 vite build）
      command: `${process.platform === "win32" ? join(".venv", "Scripts", "python.exe") : join(".venv", "bin", "python")} scripts/e2e_server.py --port 8765`,
      cwd: "..",
      url: "http://127.0.0.1:8765/api/health",
      reuseExistingServer: false,
      timeout: 120_000,
      env: { PYTHONUTF8: "1" },
    },
  ],
});
