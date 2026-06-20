import { expect, type Page } from "@playwright/test";

// Compose admin credentials (configs/server.docker.toml -> [auth]).
export const ADMIN_USER = process.env.E2E_ADMIN_USER ?? "admin";
export const ADMIN_PASS = process.env.E2E_ADMIN_PASS ?? "change-me";

// The three agents the e2e compose stack boots (base agent + e2e override).
export const AGENT_IDS = ["scrapy-agent-1", "scrapy-agent-2", "scrapy-agent-3"];

// Demo Scrapy fixture (tests/fixtures/scrapy_demo). project=demo, spider=phase1.
export const DEMO_PROJECT = "demo";
export const DEMO_SPIDER = "phase1";
export const MARKER_START = "phase1 demo spider started";
export const MARKER_DONE = "phase1 demo spider done";

// Log in through the real UI and land on the app shell.
export async function login(page: Page): Promise<void> {
  await page.goto("/login");
  // Element Plus el-input sets inheritAttrs:false and forwards data-testid onto
  // the inner <input>, so the testid IS the input element (no .locator('input')).
  await page.getByTestId("login-username").fill(ADMIN_USER);
  await page.getByTestId("login-password").fill(ADMIN_PASS);
  await page.getByTestId("login-submit").click();
  await expect(page.getByTestId("app-shell")).toBeVisible({ timeout: 30_000 });
}

// Click an Element Plus el-select (identified by data-testid) and pick an
// option by its accessible name. EP options are teleported to <body> with
// role="option". Use `exact` to avoid substring collisions (e.g. the spider
// "phase1" is a substring of the artifact label "demo · demo_phase1.egg").
export async function selectOption(
  page: Page,
  testid: string,
  optionName: string,
  opts: { exact?: boolean } = {},
): Promise<void> {
  await page.getByTestId(testid).click();
  const option = page.getByRole("option", {
    name: optionName,
    exact: opts.exact ?? false,
  });
  // Auto-waits for the (single) matching option to be visible + stable.
  await option.click();
}

// Reload the task-detail page until the executions table reaches `expected`
// rows or the timeout elapses. The detail page loads once on mount and does not
// auto-refresh, so we reload to observe async dispatch fan-out.
export async function waitForExecutionCount(
  page: Page,
  expected: number,
  timeoutMs = 90_000,
): Promise<number> {
  const deadline = Date.now() + timeoutMs;
  let count = 0;
  // eslint-disable-next-line no-constant-condition
  while (true) {
    count = await page.locator('[data-testid^="execution-agent-"]').count();
    if (count >= expected) {
      return count;
    }
    if (Date.now() >= deadline) {
      return count;
    }
    await page.waitForTimeout(3_000);
    await page.reload();
    await expect(page.getByTestId("task-detail")).toBeVisible();
  }
}

// Reload the task-detail page until the (live SSE) log body contains both demo
// markers, or the timeout elapses. Returns the final log text.
export async function waitForLogMarkers(
  page: Page,
  timeoutMs = 90_000,
): Promise<string> {
  const deadline = Date.now() + timeoutMs;
  let text = "";
  // eslint-disable-next-line no-constant-condition
  while (true) {
    text = (await page.getByTestId("log-body").innerText()) ?? "";
    if (text.includes(MARKER_START) && text.includes(MARKER_DONE)) {
      return text;
    }
    if (Date.now() >= deadline) {
      return text;
    }
    await page.waitForTimeout(3_000);
    await page.reload();
    await expect(page.getByTestId("task-detail")).toBeVisible();
  }
}
