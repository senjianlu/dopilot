// TC-07: real-browser layout verification for the horizontal-overflow fix.
//
// Drives the PRODUCTION static export (what dopilot-server actually serves)
// with every /api/v1 call mocked, so the run needs no backend and no production
// data. `next dev` was tried first and does not work here: the page never
// hydrates under it, so the data-loading useEffect never runs and the table
// stays empty. The fixture deliberately carries all four aggravating factors at
// once: a very long schedule name, a longer template name, an auto-disabled
// badge and an archived-artifact mark.
//
// Usage (from the repo root):
//   corepack pnpm -C apps/web build
//   (cd apps/web/out && python3 -m http.server 3101 --bind 127.0.0.1 &)
//   BASE=http://127.0.0.1:3101 node \
//     .ai/2026-09-16/fix-console-horizontal-overflow/evidence/layout-probe.mjs
//
// Asserts, per the plan's TC-07, at EACH of 1280 / 1440 / 1920:
//   1. documentElement.scrollWidth === clientWidth (no page-level scrollbar)
//   2. the table-container needs no inner scroll — pass/fail scoped to 1440 by
//      the plan; the other widths are measured and printed as INFO
//   3. the auto-disabled badge and the archived mark are NOT clipped
//   4. the row-actions menu is reachable and reveals all four items
import pw from "/home/rabbir/Projects/dopilot/node_modules/.pnpm/@playwright+test@1.61.0/node_modules/@playwright/test/index.js";
const { chromium } = pw;

const BASE = process.env.BASE ?? "http://127.0.0.1:3100";
const LONG_NAME =
  "steammarket-spider | JUSTONEAPI STEAM_GIFT_CARD_USD_100_TAOBAO_CNY";
const LONG_TEMPLATE = `${LONG_NAME} | template`;

const template = {
  id: "tpl-1",
  name: LONG_TEMPLATE,
  description: null,
  build_artifact_id: "art-1",
  artifact_type: "scrapy",
  project: "steammarket-spider",
  version: "v1",
  command: "scrapy crawl justoneapi",
  node_strategy: "all",
  node_ids: [],
  build_artifact_archived: true,
  build_artifact_archived_at: "2026-09-10T00:00:00+00:00",
  created_at: null,
  updated_at: null,
};

const longRow = {
  id: "sch-1",
  name: LONG_NAME,
  description: null,
  enabled: false,
  max_concurrency: 1,
  execution_template_id: "tpl-1",
  trigger_type: "cron",
  interval_seconds: null,
  cron: "0 0,12 * * *",
  overrides: {},
  next_run_at: "2026-09-17T01:00:00+00:00",
  consecutive_error_count: 5,
  auto_disabled_at: "2026-09-15T03:30:00+00:00",
  auto_disabled_reason: { consecutive_errors: 5, threshold: 5, task_ids: [] },
  outcome_generation: 0,
  created_at: null,
  updated_at: null,
};

// a few ordinary rows so the table looks like the real page
const otherRows = [
  "steammarket-spider | SWAPGG 730",
  "steammarket-spider | LOOTFARM TF2_KEY_LOOTFARM_DEPOSIT_USD",
  "steammarket-spider | STEAMCOMMUNITY verify 730",
].map((name, i) => ({
  ...longRow,
  id: `sch-${i + 2}`,
  name,
  auto_disabled_at: null,
  auto_disabled_reason: null,
  consecutive_error_count: 0,
  enabled: true,
}));

const schedules = [longRow, ...otherRows];

function mockBody(pathname) {
  if (pathname.endsWith("/auth/me")) return { username: "admin" };
  if (pathname.endsWith("/schedules")) {
    return { schedules, enabled_total: otherRows.length };
  }
  if (pathname.endsWith("/templates")) return { templates: [template] };
  if (pathname.endsWith("/nodes")) return { nodes: [] };
  if (pathname.includes("/notifications/unread-count")) return { count: 0 };
  if (pathname.includes("/notifications")) {
    return { notifications: [], total: 0 };
  }
  if (pathname.endsWith("/health")) return { status: "ok" };
  return {};
}

const failures = [];
function check(label, ok, detail) {
  console.log(`${ok ? "PASS" : "FAIL"}  ${label}${detail ? ` — ${detail}` : ""}`);
  if (!ok) failures.push(label);
}

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();

await page.route("**/api/v1/**", async (route) => {
  const pathname = new URL(route.request().url()).pathname;
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(mockBody(pathname)),
  });
});

// seed the bearer token before any page script runs
await page.addInitScript(() => {
  try {
    localStorage.setItem("dopilot.token", "probe-token");
  } catch {}
});

await page.goto(`${BASE}/schedules`, { waitUntil: "networkidle" });
await page.waitForSelector('[data-testid="schedules-table"]', {
  timeout: 60_000,
});
await page.waitForSelector(`[data-testid="schedule-actions-${LONG_NAME}"]`, {
  timeout: 30_000,
});
await page.waitForTimeout(800);

console.log(`fixture: ${schedules.length} rows, longest name ${LONG_NAME.length} chars`);
console.log(`         template ${LONG_TEMPLATE.length} chars, auto-disabled badge + archived mark on row 1\n`);

// Every check runs at every viewport, except [2] whose pass/fail the plan
// scopes to 1440 (the other widths are still measured and printed for context).
for (const width of [1280, 1440, 1920]) {
  await page.setViewportSize({ width, height: 900 });
  await page.waitForTimeout(500);

  // --- 1) whole-page overflow ---------------------------------------------
  const pageM = await page.evaluate(() => {
    const de = document.documentElement;
    return { scrollW: de.scrollWidth, clientW: de.clientWidth };
  });
  check(
    `[1] viewport ${width}: page has no horizontal scrollbar`,
    pageM.scrollW === pageM.clientW,
    `scrollWidth=${pageM.scrollW} clientWidth=${pageM.clientW} overflow=${pageM.scrollW - pageM.clientW}px`,
  );

  // --- 2) inner (card) scroll; asserted at 1440 per the plan ---------------
  const inner = await page.evaluate(() => {
    const tc = document.querySelector('[data-slot="table-container"]');
    return { scrollW: tc.scrollWidth, clientW: tc.clientWidth };
  });
  const innerDetail = `scrollWidth=${inner.scrollW} clientWidth=${inner.clientW} overflow=${Math.max(0, inner.scrollW - inner.clientW)}px`;
  if (width === 1440) {
    check(
      `[2] viewport ${width}: table needs no inner horizontal scroll`,
      inner.scrollW <= inner.clientW,
      innerDetail,
    );
  } else {
    console.log(
      `INFO  [2] viewport ${width}: inner scroll not asserted at this width — ${innerDetail}`,
    );
  }

  // --- 3) badges are not clipped ------------------------------------------
  const badges = await page.evaluate((name) => {
    const out = {};
    const probe = (key, el) => {
      if (!el) return (out[key] = null);
      const cell = el.closest("td");
      const r = el.getBoundingClientRect();
      const c = cell.getBoundingClientRect();
      out[key] = {
        visible: el.checkVisibility(),
        w: Math.round(r.width),
        inside:
          r.left >= c.left - 0.5 &&
          r.right <= c.right + 0.5 &&
          r.top >= c.top - 0.5 &&
          r.bottom <= c.bottom + 0.5,
        rect: [Math.round(r.left), Math.round(r.right)],
        cell: [Math.round(c.left), Math.round(c.right)],
      };
    };
    probe(
      "autoDisabled",
      document.querySelector(`[data-testid="schedule-auto-disabled-${name}"]`),
    );
    probe("archived", document.querySelector('[data-testid="archived-indicator"]'));
    return out;
  }, LONG_NAME);

  for (const [key, v] of Object.entries(badges)) {
    check(
      `[3] viewport ${width}: ${key} badge rendered and fully inside its cell`,
      !!v && v.visible && v.inside && v.w > 0,
      v
        ? `visible=${v.visible} width=${v.w} badge=[${v.rect}] cell=[${v.cell}]`
        : "element not found",
    );
  }

  // --- 4) the actions menu is reachable and complete -----------------------
  const trigger = page.locator(`[data-testid="schedule-actions-${LONG_NAME}"]`);
  check(
    `[4] viewport ${width}: actions trigger is visible`,
    await trigger.isVisible(),
  );
  await trigger.click();
  await page.waitForTimeout(400);
  for (const act of ["tasks", "trigger", "edit", "delete"]) {
    const item = page.locator(`[data-testid="schedule-${act}-${LONG_NAME}"]`);
    check(
      `[4] viewport ${width}: menu item "${act}" is visible`,
      await item.isVisible(),
    );
  }
  await page.keyboard.press("Escape");
  await page.waitForTimeout(300);
  if (width === 1440) {
    await page.screenshot({
      path: new URL("./schedules-after-fix.png", import.meta.url).pathname,
    });
  }
  console.log("");
}

await browser.close();
console.log(
  `\n${failures.length === 0 ? "ALL CHECKS PASSED" : `FAILED CHECKS: ${failures.join("; ")}`}`,
);
process.exit(failures.length === 0 ? 0 : 1);
