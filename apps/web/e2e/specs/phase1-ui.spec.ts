import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";
import {
  AGENT_IDS,
  confirmMessageBox,
  login,
  selectOption,
  waitForExecutionCount,
  waitForLogMarkers,
} from "../helpers/ui";

// Demo Scrapy egg fixture lives at the repo root, four levels up from this spec
// (apps/web/e2e/specs -> repo root).
const EGG_PATH = fileURLToPath(
  new URL(
    "../../../../tests/fixtures/scrapy_demo/eggs/demo_phase1.egg",
    import.meta.url,
  ),
);

// Names created through the UI during this run (kept stable for selector reuse).
const TEMPLATE_NAME = "e2e-template";
const SCHEDULE_NAME = "e2e-schedule";

// Single shared page so the serial flow keeps one logged-in session and the
// state created by earlier steps (artifact -> template -> task) is visible to
// later ones.
test.describe.configure({ mode: "serial" });

let page: Page;

test.beforeAll(async ({ browser }) => {
  page = await browser.newPage();
});

test.afterAll(async () => {
  await page.close();
});

test("login and navigation loads the app shell and pages", async () => {
  await login(page);

  // Walk the primary nav; each landing page exposes a stable table/root testid.
  await page.getByTestId("nav-nodes").click();
  await expect(page.getByTestId("nodes-table")).toBeVisible();

  await page.getByTestId("nav-artifacts").click();
  await expect(page.getByTestId("artifacts-table")).toBeVisible();

  await page.getByTestId("nav-templates").click();
  await expect(page.getByTestId("templates-table")).toBeVisible();

  await page.getByTestId("nav-schedules").click();
  await expect(page.getByTestId("schedules-table")).toBeVisible();

  await page.getByTestId("nav-tasks").click();
  await expect(page.getByTestId("tasks-table")).toBeVisible();
});

test("nodes page renders the three agents as scrapy-healthy", async () => {
  await page.getByTestId("nav-nodes").click();
  await expect(page.getByTestId("nodes-table")).toBeVisible();

  // Exactly the three compose agents are persisted as nodes.
  for (const agentId of AGENT_IDS) {
    await expect(page.getByTestId(`node-agent-${agentId}`)).toBeVisible();
    // Online + healthy => green (success) badge. This is the authoritative
    // "scrapy-capable + healthy + schedulable" signal the server computes from
    // the heartbeat (capabilities.scrapy + status=healthy).
    await expect(page.getByTestId(`node-badge-${agentId}`)).toHaveClass(
      /el-tag--success/,
    );
    // The scrapy capability tag renders. Phase 1.8.2 replaced the standalone
    // scrapyd-subprocess health column with a per-capability tag column, so the
    // "scrapy-capable" signal is now this cap tag (node-cap-{agentId}-scrapy),
    // not the removed node-scrapyd-* cell.
    await expect(
      page.getByTestId(`node-cap-${agentId}-scrapy`),
    ).toBeVisible();
  }
  const rendered = await page
    .locator('[data-testid^="node-agent-"]')
    .count();
  expect(rendered).toBe(AGENT_IDS.length);
});

test("build artifacts page uploads the demo egg (not directly runnable)", async () => {
  await page.getByTestId("nav-artifacts").click();
  await expect(page.getByTestId("artifacts-table")).toBeVisible();

  // Upload the committed demo egg through the el-upload hidden file input.
  await page
    .getByTestId("artifact-upload")
    .locator('input[type="file"]')
    .setInputFiles(EGG_PATH);

  // A build-artifact row appears: type=scrapy, package format=egg.
  await expect(page.getByTestId("artifact-name-demo")).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByTestId("artifact-type-demo")).toHaveText("scrapy");
  await expect(page.getByTestId("artifact-format-demo")).toHaveText("egg");

  // Phase 1.8.1: build artifacts are NOT directly runnable — there is no run
  // control on the row. Users create an execution template (next test).
  await expect(page.getByTestId("artifact-run-demo")).toHaveCount(0);
});

test("execution templates page creates a command template and runs it", async () => {
  await page.getByTestId("nav-templates").click();
  await expect(page.getByTestId("templates-table")).toBeVisible();

  await page.getByTestId("template-create").click();
  await expect(page.getByTestId("template-dialog")).toBeVisible();

  // el-input forwards data-testid onto the inner <input>, so the testid is the
  // input element itself.
  await page.getByTestId("template-name-input").fill(TEMPLATE_NAME);

  // Pick the uploaded demo build artifact (label includes demo_phase1.egg).
  await selectOption(page, "template-artifact-select", "demo_phase1.egg");

  // Project/version are resolved read-only from the artifact.
  await expect(page.getByTestId("template-project")).toHaveValue("demo");

  // Phase 1.8.1: command-first. The command field is EDITABLE; it defaults from
  // the artifact's first spider and can be replaced with a full command.
  const command = page.getByTestId("template-command-input");
  await expect(command).toHaveValue(/scrapy crawl/);
  // Phase 1.8.2: pass duration_seconds=0 so the demo spider runs near-instantly
  // instead of waiting for its new 60-second default.
  await command.fill("scrapy crawl phase1 -a duration_seconds=0");

  await page.getByTestId("template-submit").click();
  await expect(page.getByTestId("template-dialog")).toBeHidden();

  // The template row appears, and running it lands on a task detail page.
  await expect(
    page.getByTestId(`template-name-${TEMPLATE_NAME}`),
  ).toBeVisible();
  await page.getByTestId(`template-run-${TEMPLATE_NAME}`).click();
  await expect(page).toHaveURL(/\/tasks\/[^/]+$/, { timeout: 30_000 });
  await expect(page.getByTestId("task-detail")).toBeVisible();

  // Task detail shows the three child executions...
  const count = await waitForExecutionCount(page, AGENT_IDS.length);
  expect(count).toBe(AGENT_IDS.length);
  for (const agentId of AGENT_IDS) {
    await expect(page.getByTestId(`execution-agent-${agentId}`)).toBeVisible();
  }

  // ...and the log viewer surfaces both demo markers.
  const logText = await waitForLogMarkers(page);
  expect(logText).toContain("phase1 demo spider started");
  expect(logText).toContain("phase1 demo spider done");
});

test("tasks page lists created tasks and opens a detail page", async () => {
  await page.getByTestId("nav-tasks").click();
  await expect(page.getByTestId("tasks-table")).toBeVisible();

  const viewLinks = page.locator('[data-testid^="task-view-"]');
  await expect(viewLinks.first()).toBeVisible({ timeout: 30_000 });
  expect(await viewLinks.count()).toBeGreaterThan(0);

  await viewLinks.first().click();
  await expect(page).toHaveURL(/\/tasks\/[^/]+$/);
  await expect(page.getByTestId("task-detail")).toBeVisible();
  await expect(page.getByTestId("task-status")).toBeVisible();
});

test("schedules page creates an interval schedule and trigger-now lands on a task", async () => {
  await page.getByTestId("nav-schedules").click();
  await expect(page.getByTestId("schedules-table")).toBeVisible();

  await page.getByTestId("schedule-create").click();
  await expect(page.getByTestId("schedule-dialog")).toBeVisible();

  await page.getByTestId("schedule-name-input").fill(SCHEDULE_NAME);
  // Reference the execution template created earlier (default trigger=interval).
  await selectOption(page, "schedule-template-select", TEMPLATE_NAME, {
    exact: true,
  });

  await page.getByTestId("schedule-submit").click();
  await expect(page.getByTestId("schedule-dialog")).toBeHidden();

  await expect(
    page.getByTestId(`schedule-name-${SCHEDULE_NAME}`),
  ).toBeVisible();

  // Trigger-now creates a task and navigates to its detail page.
  await page.getByTestId(`schedule-trigger-${SCHEDULE_NAME}`).click();
  await expect(page).toHaveURL(/\/tasks\/[^/]+$/, { timeout: 30_000 });
  await expect(page.getByTestId("task-detail")).toBeVisible();
});

test("nodes page offline/online/delete actions update visible state", async () => {
  await page.getByTestId("nav-nodes").click();
  await expect(page.getByTestId("nodes-table")).toBeVisible();

  // Take scrapy-agent-1 offline -> red (danger) badge, online control appears.
  // Phase 1.8.2: offline is a confirmed (ElMessageBox) action.
  const offlineTarget = "scrapy-agent-1";
  await page.getByTestId(`node-offline-${offlineTarget}`).click();
  await confirmMessageBox(page);
  await expect(page.getByTestId(`node-badge-${offlineTarget}`)).toHaveClass(
    /el-tag--danger/,
  );
  await expect(page.getByTestId(`node-online-${offlineTarget}`)).toBeVisible();

  // Bring it back online -> green (success) badge, schedulable again.
  // Online is not a confirmed action (no message box).
  await page.getByTestId(`node-online-${offlineTarget}`).click();
  await expect(page.getByTestId(`node-badge-${offlineTarget}`)).toHaveClass(
    /el-tag--success/,
  );

  // Soft-delete scrapy-agent-3 -> gray (info) badge, no action controls left.
  // Phase 1.8.2: delete is a confirmed (ElMessageBox) action.
  const deleteTarget = "scrapy-agent-3";
  await page.getByTestId(`node-delete-${deleteTarget}`).click();
  await confirmMessageBox(page);
  await expect(page.getByTestId(`node-badge-${deleteTarget}`)).toHaveClass(
    /el-tag--info/,
  );
  await expect(
    page.getByTestId(`node-offline-${deleteTarget}`),
  ).toHaveCount(0);
  await expect(
    page.getByTestId(`node-delete-${deleteTarget}`),
  ).toHaveCount(0);
});
