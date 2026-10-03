import { defineConfig } from "@playwright/test";
import { resolve } from "node:path";

export default defineConfig({
  testDir: "./tests", fullyParallel: false, workers: 1, retries: 0,
  timeout: 90_000,
  expect: { timeout: 20_000 },
  use: { baseURL: "http://127.0.0.1:3100", browserName: "chromium", trace: "retain-on-failure", actionTimeout: 30_000 },
  webServer: [
    { command: "uv run --frozen python -m app.test_server", cwd: resolve(__dirname, "../backend"),
      url: "http://127.0.0.1:8100/api/v1/health", reuseExistingServer: false, timeout: 180_000 },
    { command: "pnpm start", cwd: __dirname, url: "http://127.0.0.1:3100",
      reuseExistingServer: false, timeout: 180_000, env: {
        NEXT_TELEMETRY_DISABLED: "1",
        NODE_OPTIONS: `--import=${resolve(__dirname, "test-support/network-guard.mjs")}`,
      } },
  ],
});
