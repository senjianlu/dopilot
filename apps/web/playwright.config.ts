import { defineConfig, devices } from "@playwright/test";

// Phase 1.8 browser e2e config.
//
// These specs drive the BUNDLED PRODUCTION SPA served by the Docker `server`
// container at http://localhost:5000 — NOT a Vite dev server. The container
// stack is brought up by scripts/smoke-phase1-ui.sh (one server, three agents,
// PostgreSQL, Redis, migrate). Playwright never starts a webServer here.
//
// The specs mutate shared backend state (upload, run, node offline/online/
// delete) and are order-dependent, so we run a single worker, no parallelism,
// and no retries (a retry would replay against already-mutated state).
const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:5000";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/*.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  // Generous global timeout: a step may wait on Scrapy dispatch + log markers.
  timeout: 120_000,
  expect: { timeout: 30_000 },
  forbidOnly: !!process.env.CI,
  reporter: [
    ["list"],
    ["html", { outputFolder: "playwright-report", open: "never" }],
  ],
  outputDir: "test-results",
  use: {
    baseURL,
    headless: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    actionTimeout: 30_000,
    navigationTimeout: 30_000,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
