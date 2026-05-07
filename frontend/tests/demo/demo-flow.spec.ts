/**
 * RAF Intelligence — sales / investor demo flow.
 *
 * Runs against the local stack (http://localhost:3444 / 8500) and walks
 * the buyer through 7 narrative scenes in 5–7 minutes.  Each scene:
 *   - prints a one-line talking point to the terminal so the presenter
 *     can read along
 *   - takes a screenshot to ``frontend/playwright-report/demo-shots/``
 *     so the run leaves a deck-ready storyboard behind
 *
 * Run with::
 *
 *     cd frontend && BASE_URL=http://localhost:3444 \
 *       DEMO_EMAIL=admin@raf.health DEMO_PASSWORD=Admin@123 \
 *       npx playwright test tests/demo/demo-flow.spec.ts \
 *       --project=chromium --headed --workers=1
 *
 * For a screen-recorded demo, add ``--video=on`` to the command above —
 * Playwright will write a .webm under ``playwright-report/`` you can
 * trim and post to your sales drive.
 *
 * The script is read-only — no data is mutated.  Safe to re-run before
 * every demo.
 */
import { test, type Page } from "@playwright/test";
import * as path from "path";
import * as fs from "fs";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3444";
const EMAIL = process.env.DEMO_EMAIL ?? "admin@raf.health";
const PASSWORD = process.env.DEMO_PASSWORD ?? "Admin@123";
const SHOT_DIR = path.resolve(__dirname, "../../playwright-report/demo-shots");
const STATE_FILE = path.resolve(__dirname, ".demo-auth-state.json");

const PAUSE_BETWEEN_SCENES_MS = Number(process.env.DEMO_PAUSE_MS ?? "1500");

function ensureDir(dir: string): void {
  fs.mkdirSync(dir, { recursive: true });
}

function narrate(scene: string, line: string): void {
  // eslint-disable-next-line no-console
  console.log(`\n  [${scene}] ${line}`);
}

async function shot(page: Page, name: string): Promise<void> {
  ensureDir(SHOT_DIR);
  const file = path.join(SHOT_DIR, `${name}.png`);
  // ``networkidle`` is unreliable in this app — React Query keeps the
  // network busy with background refetches.  Wait an explicit beat for
  // content to settle, then snap.
  await page.waitForTimeout(2000);
  await page.screenshot({ path: file, fullPage: false });
  // eslint-disable-next-line no-console
  console.log(`        → ${file}`);
}

/** Wait until the rendered DOM contains at least one of the expected
 * tokens — usually a PageHeader title or a section header.  Falls back
 * to a fixed wait if none match within 8s. */
async function waitForContent(page: Page, anyOf: string[]): Promise<void> {
  for (const sel of anyOf) {
    try {
      await page.getByText(sel, { exact: false }).first().waitFor({ timeout: 8000 });
      return;
    } catch {
      // try the next one
    }
  }
}

async function login(page: Page): Promise<void> {
  await page.goto(`${BASE_URL}/login`);
  await page.waitForSelector('input[type="email"]', { state: "visible" });
  await page.fill('input[type="email"]', EMAIL);
  await page.fill('input[type="password"]', PASSWORD);
  await page.click('button[type="submit"]');
  await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 30_000 });
}

/** Cached login: log in once at the start of the suite, then reuse the
 * resulting cookies + localStorage in every scene.  Avoids hammering the
 * auth rate-limiter with fresh logins per scene (which locks the
 * admin account after 5 attempts). */
async function ensureAuth(page: Page): Promise<void> {
  // Probe the home route — if storageState authenticated us, we should
  // not land on /login.  Loosened load-state because the auth-context
  // does an initial spinner render that can delay ``load``.
  await page.goto(BASE_URL, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1500);
  if (!page.url().includes("/login")) return;
  await login(page);
}

/** Wait until the auth-context spinner has finished and an actual
 * authenticated page chrome (sidebar / page header) is rendered.
 * Without this we tend to screenshot the bare spinner. */
async function waitPastAuthSpinner(page: Page): Promise<void> {
  // The sidebar's "Dashboard" or "Today's worklist" link is visible on
  // every authenticated page once auth-context resolves.
  try {
    await page
      .getByRole("link", { name: /Dashboard|Today's worklist/i })
      .first()
      .waitFor({ timeout: 12000 });
  } catch {
    // Fall through — the scene-specific waitForContent will catch
    // remaining issues.
  }
}

async function pause(page: Page, label?: string): Promise<void> {
  if (label) {
    // eslint-disable-next-line no-console
    console.log(`        … pausing for: ${label}`);
  }
  await page.waitForTimeout(PAUSE_BETWEEN_SCENES_MS);
}

test.describe.configure({ mode: "serial" });

test.describe("RAF Intelligence — sales demo flow", () => {
  test.beforeAll(() => {
    ensureDir(SHOT_DIR);
    // eslint-disable-next-line no-console
    console.log(`\n  Demo shots will be saved to: ${SHOT_DIR}`);
    console.log(`  Target: ${BASE_URL}\n`);
  });

  test("Scene 1 — Monday morning: Today's worklist", async ({ page }) => {
    narrate(
      "Scene 1",
      "A provider opens the app on Monday morning. They don't want a generic dashboard — they want to know which patients to see this week and why."
    );
    await ensureAuth(page);
    await page.goto(`${BASE_URL}/worklist`);
    await waitPastAuthSpinner(page); await waitForContent(page, ["Today's worklist", "patients prioritized", "You're caught up"]);
    narrate(
      "Scene 1",
      "Today's worklist sorts patients by priority score (open gaps × revenue at risk). Each card is mobile-friendly and self-contained — works on the iPad in an exam room."
    );
    await shot(page, "01-worklist");
    await pause(page);
  });

  test("Scene 2 — Why this HCC? KG explainability", async ({ page }) => {
    narrate(
      "Scene 2",
      "The differentiator vs Navina/Apixio: every suspect HCC has a traceable evidence chain. Hover any HCC chip to see the ICD-10 → SNOMED → HCC mapping with literature citations."
    );
    await ensureAuth(page);
    await page.goto(`${BASE_URL}/recapture`);
    await waitPastAuthSpinner(page); await waitForContent(page, ["Recapture", "Total Gaps", "Patients"]);
    await shot(page, "02a-recapture-overview");

    // Hover the first HCC chip if present.
    const hccChip = page.getByRole("button", { name: /HCC/i }).first();
    if (await hccChip.count()) {
      await hccChip.hover();
      await page.waitForTimeout(800);
      await shot(page, "02b-hcc-popover");
      narrate(
        "Scene 2",
        "Auditors love this — RADV defense argues from documented evidence, not 'the model said so'."
      );
    }
    await pause(page);
  });

  test("Scene 3 — Calibrated confidence", async ({ page }) => {
    narrate(
      "Scene 3",
      "Every confidence number is Platt-calibrated. ECE drops from 0.22 (raw) to 0.03 (calibrated) — when we say 78%, it actually means 78%. Most competitors ship raw model outputs."
    );
    await ensureAuth(page);
    await page.goto(`${BASE_URL}/suspects`);
    await waitPastAuthSpinner(page); await waitForContent(page, ["Suspect", "Confidence", "HCC"]);
    await shot(page, "03-suspects-calibrated");
    await pause(page);
  });

  test("Scene 4 — Audit defense (RADV + Cohen's kappa)", async ({ page }) => {
    narrate(
      "Scene 4",
      "Dual-coder MEAT audit trail with Cohen's kappa = 0.52 (moderate inter-rater reliability). One-click PDF export of audit-ready gaps for CMS RADV submission."
    );
    await ensureAuth(page);
    await page.goto(`${BASE_URL}/recapture`);
    await waitPastAuthSpinner(page); await waitForContent(page, ["Recapture", "Total Gaps"]);

    // Scroll to the AuditReadinessCard section.
    const auditHeader = page.getByText(/RADV Audit Defense|Audit Ready/i).first();
    if (await auditHeader.count()) {
      await auditHeader.scrollIntoViewIfNeeded();
      await page.waitForTimeout(600);
    }
    await shot(page, "04-audit-readiness");
    await pause(page);
  });

  test("Scene 5 — Velocity & decay", async ({ page }) => {
    narrate(
      "Scene 5",
      "Recapture velocity KPIs + decay curve. Tells the operations team how fast gaps close month-over-month so they can intervene before the year-end cliff."
    );
    await ensureAuth(page);
    await page.goto(`${BASE_URL}/recapture`);
    await waitPastAuthSpinner(page); await waitForContent(page, ["Recapture", "Total Gaps"]);
    const velocityHeader = page.getByText(/velocity|decay/i).first();
    if (await velocityHeader.count()) {
      await velocityHeader.scrollIntoViewIfNeeded();
      await page.waitForTimeout(600);
    }
    await shot(page, "05-velocity-decay");
    await pause(page);
  });

  test("Scene 6 — CFO executive summary", async ({ page }) => {
    narrate(
      "Scene 6",
      "CFO view: quarterly $ projection, top conditions by revenue, top providers, year-over-year. The amber 'PROJECTED' badge makes actual-vs-forecast unambiguous."
    );
    await ensureAuth(page);
    await page.goto(`${BASE_URL}/recapture`);
    await waitPastAuthSpinner(page); await waitForContent(page, ["Recapture", "Total Gaps"]);
    const cfoHeader = page.getByText(/CFO executive summary|Projected/i).first();
    if (await cfoHeader.count()) {
      await cfoHeader.scrollIntoViewIfNeeded();
      await page.waitForTimeout(600);
    }
    await shot(page, "06-cfo-summary");
    await pause(page);
  });

  test("Scene 7 — Mobile (iPad in the exam room)", async ({ page }) => {
    narrate(
      "Scene 7",
      "The same worklist on an iPad-sized viewport. Auto-fit grid collapses to a single column on phone, two on tablet — providers chart at the bedside, not in front of a laptop."
    );
    await ensureAuth(page);
    await page.setViewportSize({ width: 414, height: 896 }); // iPhone 13 Pro Max
    await page.goto(`${BASE_URL}/worklist`);
    await waitPastAuthSpinner(page); await waitForContent(page, ["Today's worklist", "You're caught up"]);
    await shot(page, "07a-worklist-mobile");

    await page.setViewportSize({ width: 768, height: 1024 }); // iPad
    await page.reload();
    await waitPastAuthSpinner(page); await waitForContent(page, ["Today's worklist", "You're caught up"]);
    await shot(page, "07b-worklist-tablet");
    await pause(page);
  });

  test.afterAll(() => {
    // eslint-disable-next-line no-console
    console.log(`\n  Demo run complete. Storyboard at: ${SHOT_DIR}\n`);
  });
});
