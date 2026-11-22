import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  use: {
    baseURL: "http://127.0.0.1:5179",
    viewport: { width: 1000, height: 800 },
    // 无头模式下用软件 WebGL（SwiftShader），地图才能渲染
    launchOptions: { args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] },
  },
  webServer: {
    command: "npx vite --port 5179 --strictPort --host 127.0.0.1",
    url: "http://127.0.0.1:5179/demo/index.html",
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
