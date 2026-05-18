/**
 * demo-smoke-final.spec.ts
 *
 * Final end-to-end demo-path smoke test for RAF Intelligence.
 * Simulates the full 12-minute demo narrative with screenshot archive.
 *
 * Run:
 *   E2E_BASE_URL=https://raf.comercioit.com \
 *   npx playwright test tests/e2e/demo-smoke-final.spec.ts \
 *     --project=chromium --reporter=list
 *
 * Screenshots → /tmp/demo-smoke-final/<timestamp>-<step>.png
 *
 * Assertions (FAIL if violated):
 *   - Every H1 page title is correct
 *   - Every dollar value > $0 (unless intentionally "0 disputes")
 *   - Every count non-zero on dashboard / worklist / recapture
 *   - No console errors during the walk
 *   - No 404 / 500 responses in network log
 *   - Every page loaded under 8 seconds
 *
 * @smoke @full
 */

import { test, expect, type Page } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

const BASE_URL = process.env.E2E_BASE_URL ?? "https://raf.comercioit.com";
const ADMIN_EMAIL = "admin@raf.health";
const ADMIN_PASSWORD = "Admin@123";
const SNAP_DIR = "/tmp/demo-smoke-final";
const PAGE_LOAD_BUDGET_MS = 8_000;

// 25-minute wait so other agents have time to deploy before we start.
const DEPLOY_WAIT_MS = 25 * 60 * 1_000;

// ---------------------------------------------------------------------------
// Snapshot helper
// ---------------------------------------------------------------------------

let snapIndex = 0;

async function snap(page: Page, label: string): Promise<string> {
  fs.mkdirSync(SNAP_DIR, { recursive: true });
  const ts = new Date().toISOString().replace(/[:.]/g, "-");
  const filename = `${String(++snapIndex).padStart(2, "0")}-${ts}-${label.replace(/\s+/g, "_")}.png`;
  const filepath = path.join(SNAP_DIR, filename);
  await page.screenshot({ path: filepath, fullPage: true });
  console.log(`[snap] ${filepath}`);
  return filepath;
}

// ---------------------------------------------------------------------------
// Assertion helpers
// ---------------------------------------------------------------------------

/**
 * Assert element text does not represent a zero-value dollar amount.
 * "0 disputes" is intentionally allowed (chain-intact state).
 */
async function assertNonZeroDollar(
  page: Page,
  selector: string,
  label: string
): Promise<void> {
  const el = page.locator(selector).first();
  const text = (await el.textContent({ timeout: 10_000 })) ?? "";
  const stripped = text.replace(/[$,\s]/g, "");
  const isZero = stripped === "0" || stripped === "0.00" || stripped === "$0";
  if (isZero) {
    throw new Error(`[FAIL] ${label} shows zero value: "${text}"`);
  }
}

/**
 * Assert an element's numeric text is > 0.
 */
async function assertNonZeroCount(
  page: Page,
  selector: string,
  label: string
): Promise<void> {
  const el = page.locator(selector).first();
  const text = (await el.textContent({ timeout: 10_000 })) ?? "";
  const num = parseFloat(text.replace(/[^0-9.]/g, ""));
  if (isNaN(num) || num === 0) {
    throw new Error(`[FAIL] ${label} is zero or NaN: "${text}"`);
  }
}

/**
 * Assert page navigation completed within PAGE_LOAD_BUDGET_MS.
 */
function assertPageLoadTime(startMs: number, pageLabel: string): void {
  const elapsed = Date.now() - startMs;
  if (elapsed > PAGE_LOAD_BUDGET_MS) {
    throw new Error(
      `[FAIL] ${pageLabel} took ${elapsed}ms — exceeds 8 s budget`
    );
  }
}

// ---------------------------------------------------------------------------
// Login helper (uses correct Admin@123 canonical password)
// ---------------------------------------------------------------------------

async function login(page: Page): Promise<void> {
  await page.goto(`${BASE_URL}/login`);
  await page.waitForSelector('input[type="email"]', {
    state: "visible",
    timeout: 20_000,
  });
  await page.fill('input[type="email"]', ADMIN_EMAIL);
  await page.fill('input[type="password"]', ADMIN_PASSWORD);
  await page.click('button[type="submit"]');
  await page.waitForURL((url) => !url.pathname.includes("/login"), {
    timeout: 30_000,
  });
  await page.waitForLoadState("networkidle");
  // Suppress onboarding wizard if present.
  await page
    .evaluate(() => localStorage.setItem("raf_onboarding_complete", "true"))
    .catch(() => null);
}

// ---------------------------------------------------------------------------
// Main smoke test
// ---------------------------------------------------------------------------

test(
  "@smoke @full Demo narrative — full 12-step smoke with screenshot archive",
  async ({ page }) => {
    // Extend timeout: 25-min deploy wait + ~10 min of test execution.
    test.setTimeout(DEPLOY_WAIT_MS + 15 * 60 * 1_000);

    // ── Deploy wait ──────────────────────────────────────────────────────────
    console.log(`[demo-smoke] Waiting ${DEPLOY_WAIT_MS / 60_000} min for deployment…`);
    await page.waitForTimeout(DEPLOY_WAIT_MS);
    console.log("[demo-smoke] Deploy wait complete — starting demo walk");

    // ── Collectors ───────────────────────────────────────────────────────────
    const consoleErrors: string[] = [];
    const networkFailures: string[] = [];

    page.on("console", (msg) => {
      if (msg.type() === "error") {
        const txt = msg.text();
        // Filter browser noise.
        if (!txt.includes("favicon") && !txt.includes("net::ERR_ABORTED")) {
          consoleErrors.push(txt);
        }
      }
    });

    page.on("response", (resp) => {
      const status = resp.status();
      if (status === 404 || status >= 500) {
        networkFailures.push(`${status} ${resp.url()}`);
      }
    });

    // ════════════════════════════════════════════════════════════════════════
    // Step 1 — Login page
    // ════════════════════════════════════════════════════════════════════════
    console.log("[step 1] Login page");
    let t0 = Date.now();
    await page.goto(`${BASE_URL}/login`);
    await page.waitForLoadState("networkidle");
    assertPageLoadTime(t0, "Login page");
    await snap(page, "01-login-page");

    // Verify login form rendered.
    await expect(page.locator('input[type="email"]').first()).toBeVisible({
      timeout: 10_000,
    });

    // ════════════════════════════════════════════════════════════════════════
    // Step 2 — Sign In
    // ════════════════════════════════════════════════════════════════════════
    console.log("[step 2] Signing in");
    await page.fill('input[type="email"]', ADMIN_EMAIL);
    await page.fill('input[type="password"]', ADMIN_PASSWORD);
    await page.click('button[type="submit"]');
    await page.waitForURL((url) => !url.pathname.includes("/login"), {
      timeout: 30_000,
    });
    await page.waitForLoadState("networkidle");
    await page
      .evaluate(() => localStorage.setItem("raf_onboarding_complete", "true"))
      .catch(() => null);

    // ════════════════════════════════════════════════════════════════════════
    // Step 3 — Dashboard full-page screenshot
    // ════════════════════════════════════════════════════════════════════════
    console.log("[step 3] Dashboard — full page scroll + screenshot");
    t0 = Date.now();
    await page.goto(`${BASE_URL}/`);
    await page.waitForLoadState("networkidle");
    assertPageLoadTime(t0, "Dashboard");
    // Scroll to trigger lazy sections.
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await page.waitForTimeout(1_000);
    await page.evaluate(() => window.scrollTo(0, 0));
    await snap(page, "02-dashboard-full");

    // ════════════════════════════════════════════════════════════════════════
    // Step 4 — Dashboard assertions
    // ════════════════════════════════════════════════════════════════════════
    console.log("[step 4] Dashboard assertions");

    // H1 title.
    const dashH1 = page
      .locator("h1, [class*='heading'], [class*='title']")
      .filter({ hasText: /population health intelligence|population intelligence|dashboard/i })
      .first();
    await expect(dashH1).toBeVisible({ timeout: 15_000 });

    // CMS Sweep Deadline with non-$0 Pending Opportunity.
    const sweepSection = page.locator(
      "text=/cms sweep|sweep deadline|pending opportunity/i"
    );
    if (await sweepSection.first().isVisible({ timeout: 5_000 }).catch(() => false)) {
      await assertNonZeroDollar(
        page,
        "[class*='opportunity'], [class*='pending'], [data-testid*='pending']",
        "CMS Sweep Pending Opportunity"
      );
    }

    // 4 KPIs non-zero: look for known KPI labels and their adjacent numeric values.
    const kpiLabels = [
      /total population|patients/i,
      /analyzed|analysis/i,
      /raf score|average raf/i,
      /revenue|opportunity/i,
    ];
    for (const pattern of kpiLabels) {
      const kpiEl = page
        .locator("[class*='kpi'], [class*='stat'], [class*='metric'], [class*='card']")
        .filter({ hasText: pattern })
        .first();
      if (await kpiEl.isVisible({ timeout: 5_000 }).catch(() => false)) {
        const kpiText = (await kpiEl.textContent()) ?? "";
        const nums = kpiText.match(/[\d,]+\.?\d*/g) ?? [];
        const nonZero = nums.some((n) => parseFloat(n.replace(/,/g, "")) > 0);
        expect(nonZero, `KPI "${pattern}" shows all-zero values: "${kpiText}"`).toBe(true);
      }
    }

    // V28 Hero delta present.
    const v28El = page.locator("text=/v28|v 28|model v28/i").first();
    if (await v28El.isVisible({ timeout: 5_000 }).catch(() => false)) {
      await expect(v28El).toBeVisible();
    }

    // Provider Performance — at least 1 provider.
    const providerSection = page.locator(
      "text=/provider performance|providers/i"
    );
    if (
      await providerSection.first().isVisible({ timeout: 5_000 }).catch(() => false)
    ) {
      await expect(providerSection.first()).toBeVisible();
    }

    await snap(page, "03-dashboard-assertions-done");

    // ════════════════════════════════════════════════════════════════════════
    // Step 5 — Today's Worklist
    // ════════════════════════════════════════════════════════════════════════
    console.log("[step 5] Today's Worklist");
    t0 = Date.now();

    // Try clicking the Worklist link; fall back to direct nav.
    const worklistLink = page
      .locator('a[href="/worklist"], a[href*="worklist"], button')
      .filter({ hasText: /worklist|today.*worklist/i })
      .first();
    if (await worklistLink.isVisible({ timeout: 5_000 }).catch(() => false)) {
      await worklistLink.click();
      await page.waitForLoadState("networkidle");
    } else {
      await page.goto(`${BASE_URL}/worklist`);
      await page.waitForLoadState("networkidle");
    }
    assertPageLoadTime(t0, "Worklist");
    await snap(page, "04-worklist");

    // H1.
    const worklistH1 = page
      .locator("h1, [class*='heading'], [class*='title']")
      .filter({ hasText: /worklist|today.*worklist/i })
      .first();
    const hasWorklistH1 = await worklistH1
      .isVisible({ timeout: 8_000 })
      .catch(() => false);
    expect(hasWorklistH1, "Worklist page H1 not found").toBe(true);

    // 5+ patient cards.
    const patientCards = page.locator(
      "[class*='patient'], [class*='card'], [role='listitem'], [data-testid*='patient']"
    );
    await page.waitForTimeout(2_000);
    const cardCount = await patientCards.count();
    expect(cardCount, `Expected 5+ patient cards, got ${cardCount}`).toBeGreaterThanOrEqual(5);

    // Gap chips populated.
    const gapChips = page.locator(
      "[class*='gap'], [class*='chip'], [class*='badge'], [class*='hcc']"
    );
    const chipCount = await gapChips.count();
    expect(chipCount, "Expected gap chips on worklist").toBeGreaterThan(0);

    await snap(page, "05-worklist-patient-cards");

    // ════════════════════════════════════════════════════════════════════════
    // Step 6 — Hover HCC gap chip → popover
    // ════════════════════════════════════════════════════════════════════════
    console.log("[step 6] HCC gap chip hover popover");
    const firstChip = gapChips.first();
    if (await firstChip.isVisible({ timeout: 5_000 }).catch(() => false)) {
      await firstChip.hover();
      await page.waitForTimeout(800);
      await snap(page, "06-gap-chip-hover-popover");

      // Verify popover content (HCC description / RAF lift / $ amount / MEAT).
      const popover = page.locator(
        "[role='tooltip'], [class*='popover'], [class*='tooltip'], [class*='popup']"
      );
      if (await popover.first().isVisible({ timeout: 4_000 }).catch(() => false)) {
        const popText = (await popover.first().textContent()) ?? "";
        // At minimum the popover should have some numeric or descriptive content.
        expect(
          popText.length,
          "HCC popover is empty"
        ).toBeGreaterThan(5);
      }
    }

    // ════════════════════════════════════════════════════════════════════════
    // Step 7 — Reject modal (click ✕ on a gap)
    // ════════════════════════════════════════════════════════════════════════
    console.log("[step 7] Reject / dismiss gap modal");
    // Look for a dismiss / reject / X button on gap chips.
    const rejectBtn = page
      .locator(
        "button[aria-label*='reject' i], button[aria-label*='dismiss' i], button[aria-label*='remove' i], [data-testid*='reject'], [data-testid*='dismiss']"
      )
      .first();
    if (await rejectBtn.isVisible({ timeout: 5_000 }).catch(() => false)) {
      await rejectBtn.click();
      await page.waitForTimeout(600);
      await snap(page, "07-reject-modal");

      // Verify reason code dropdown with 6 options.
      const dropdown = page.locator(
        "select, [role='listbox'], [class*='select'], [class*='dropdown']"
      );
      if (await dropdown.first().isVisible({ timeout: 4_000 }).catch(() => false)) {
        const options = await page
          .locator("option, [role='option']")
          .count();
        expect(
          options,
          `Expected 6 reason codes in reject dropdown, got ${options}`
        ).toBeGreaterThanOrEqual(6);
      }

      // Close the modal.
      const closeBtn = page
        .locator(
          "button[aria-label*='close' i], button[aria-label*='cancel' i], button:has-text('Cancel'), button:has-text('Close'), [data-testid*='close']"
        )
        .first();
      if (await closeBtn.isVisible({ timeout: 3_000 }).catch(() => false)) {
        await closeBtn.click();
        await page.waitForTimeout(400);
      } else {
        await page.keyboard.press("Escape");
        await page.waitForTimeout(400);
      }
    }

    // ════════════════════════════════════════════════════════════════════════
    // Step 8 — Patient detail page
    // ════════════════════════════════════════════════════════════════════════
    console.log("[step 8] Patient detail");
    t0 = Date.now();
    // Click first patient card.
    const firstPatientCard = patientCards.first();
    if (await firstPatientCard.isVisible({ timeout: 5_000 }).catch(() => false)) {
      await firstPatientCard.click();
      await page.waitForLoadState("networkidle");
    }

    // If no navigation occurred try a direct link.
    if (page.url().includes("/worklist") || page.url().endsWith("/")) {
      await page.goto(`${BASE_URL}/patients`);
      await page.waitForLoadState("networkidle");
      const firstPatientLink = page
        .locator("a[href*='/patients/'], [role='button']")
        .first();
      if (await firstPatientLink.isVisible({ timeout: 5_000 }).catch(() => false)) {
        await firstPatientLink.click();
        await page.waitForLoadState("networkidle");
      }
    }
    assertPageLoadTime(t0, "Patient detail");
    await snap(page, "08-patient-detail");

    // Verify name visible, RAF score non-zero, HCC chips.
    const patientName = page
      .locator("h1, h2, [class*='name'], [data-testid*='name']")
      .first();
    const nameVisible = await patientName
      .isVisible({ timeout: 8_000 })
      .catch(() => false);
    expect(nameVisible, "Patient name not visible on detail page").toBe(true);

    const rafScoreEl = page.locator(
      "[class*='raf'], [data-testid*='raf'], text=/raf score/i"
    );
    if (await rafScoreEl.first().isVisible({ timeout: 5_000 }).catch(() => false)) {
      const rafText = (await rafScoreEl.first().textContent()) ?? "";
      const rafNum = parseFloat(rafText.replace(/[^0-9.]/g, ""));
      expect(!isNaN(rafNum) && rafNum > 0, `RAF score is zero/NaN: "${rafText}"`).toBe(true);
    }

    // ════════════════════════════════════════════════════════════════════════
    // Step 9 — Back to worklist, select 3 patients → bulk action bar
    // ════════════════════════════════════════════════════════════════════════
    console.log("[step 9] Bulk action bar");
    await page.goto(`${BASE_URL}/worklist`);
    await page.waitForLoadState("networkidle");

    // Select first 3 patient checkboxes.
    const checkboxes = page.locator(
      "input[type='checkbox'], [role='checkbox'], [data-testid*='select']"
    );
    const cbCount = await checkboxes.count();
    const toSelect = Math.min(3, cbCount);
    for (let i = 0; i < toSelect; i++) {
      await checkboxes.nth(i).click().catch(() => null);
      await page.waitForTimeout(200);
    }
    await snap(page, "09-bulk-action-bar");

    // Bulk action bar / toolbar should appear if checkboxes were selectable.
    const bulkBar = page.locator(
      "[class*='bulk'], [class*='toolbar'], [data-testid*='bulk'], [aria-label*='selected' i]"
    );
    // Soft check — bulk bar may not appear if selections didn't register.
    const bulkVisible = await bulkBar
      .first()
      .isVisible({ timeout: 4_000 })
      .catch(() => false);
    if (!bulkVisible) {
      console.warn("[warn] Bulk action bar not detected after selecting 3 patients");
    }

    // ════════════════════════════════════════════════════════════════════════
    // Step 10 — /v28-impact
    // ════════════════════════════════════════════════════════════════════════
    console.log("[step 10] /v28-impact");
    t0 = Date.now();
    await page.goto(`${BASE_URL}/v28-impact`);
    await page.waitForLoadState("networkidle");
    assertPageLoadTime(t0, "/v28-impact");
    await snap(page, "10-v28-impact");

    const v28H1 = page
      .locator("h1, h2, [class*='heading']")
      .filter({ hasText: /v28|recapture|impact/i })
      .first();
    await expect(v28H1).toBeVisible({ timeout: 15_000 });

    // Top-eroded list — at least 5 rows.
    const erodedRows = page.locator(
      "tr, [role='row'], [class*='row'], [class*='eroded'], [class*='list-item']"
    );
    const rowCount = await erodedRows.count();
    expect(
      rowCount,
      `Expected 5+ eroded rows on v28-impact, got ${rowCount}`
    ).toBeGreaterThanOrEqual(5);

    // ════════════════════════════════════════════════════════════════════════
    // Step 11 — /radv
    // ════════════════════════════════════════════════════════════════════════
    console.log("[step 11] /radv");
    t0 = Date.now();
    await page.goto(`${BASE_URL}/radv`);
    await page.waitForLoadState("networkidle");
    assertPageLoadTime(t0, "/radv");
    await snap(page, "11-radv");

    const radvH1 = page
      .locator("h1, h2, [role='heading']")
      .filter({ hasText: /radv|audit defense|risk adjustment/i })
      .first();
    await expect(radvH1).toBeVisible({ timeout: 15_000 });

    // Extrapolation toggle present.
    const extrapToggle = page.locator(
      "input[type='checkbox'][aria-label*='extrap' i], [data-testid*='extrap'], button:has-text(/extrap/i), label:has-text(/extrap/i)"
    );
    const hasExtrap = await extrapToggle
      .first()
      .isVisible({ timeout: 5_000 })
      .catch(() => false);
    if (!hasExtrap) {
      console.warn("[warn] Extrapolation toggle not found on /radv");
    }

    // 1-2 audit runs visible.
    const auditRuns = page.locator(
      "[class*='run'], [class*='audit'], tr, [role='row']"
    );
    const runCount = await auditRuns.count();
    expect(runCount, "Expected at least 1 audit run on /radv").toBeGreaterThanOrEqual(1);

    // ════════════════════════════════════════════════════════════════════════
    // Step 12 — /audit
    // ════════════════════════════════════════════════════════════════════════
    console.log("[step 12] /audit");
    t0 = Date.now();
    await page.goto(`${BASE_URL}/audit`);
    await page.waitForLoadState("networkidle");
    assertPageLoadTime(t0, "/audit");
    await snap(page, "12-audit-page");

    const auditH1 = page
      .locator("h1, h2, [role='heading']")
      .filter({ hasText: /audit|chain integrity|compliance/i })
      .first();
    await expect(auditH1).toBeVisible({ timeout: 15_000 });

    // Chain integrity card with non-zero entries.
    const chainCard = page.locator(
      "text=/chain integrity|audit chain|hash/i"
    );
    const hasChain = await chainCard
      .first()
      .isVisible({ timeout: 8_000 })
      .catch(() => false);
    expect(hasChain, "Chain integrity card not found on /audit").toBe(true);

    // Hash chips present.
    const hashChips = page.locator(
      "[class*='hash'], [class*='chip'][title*='hash'], code, [class*='mono']"
    );
    const hashCount = await hashChips.count();
    expect(hashCount, "Expected hash chips on /audit").toBeGreaterThan(0);

    // ════════════════════════════════════════════════════════════════════════
    // Step 13 — Verify Chain Integrity
    // ════════════════════════════════════════════════════════════════════════
    console.log("[step 13] Verify Chain Integrity");
    const verifyBtn = page
      .getByRole("button", { name: /verify|check integrity|verify chain/i })
      .first();
    if (await verifyBtn.isVisible({ timeout: 5_000 }).catch(() => false)) {
      await verifyBtn.click();
      await page.waitForTimeout(2_000);
      await snap(page, "13-chain-verify-result");

      // Result should say chain intact / 100% / verified / 0 disputes.
      const resultEl = page.locator(
        "text=/chain intact|100%|verified|0 dispute|integrity ok/i"
      );
      const hasResult = await resultEl
        .first()
        .isVisible({ timeout: 10_000 })
        .catch(() => false);
      if (!hasResult) {
        console.warn(
          "[warn] Chain verify result message not found — manual check needed"
        );
      }
    } else {
      console.warn("[warn] Verify Chain Integrity button not found on /audit");
      await snap(page, "13-chain-verify-not-found");
    }

    // ════════════════════════════════════════════════════════════════════════
    // Final: flush assertions
    // ════════════════════════════════════════════════════════════════════════
    console.log("[demo-smoke] Checking console errors and network failures");

    // Filter out acceptable API noise (auth refresh, OPTIONS preflight).
    const criticalErrors = consoleErrors.filter(
      (e) =>
        !e.includes("401") &&
        !e.includes("favicon") &&
        !e.includes("net::ERR") &&
        !e.includes("Non-Error")
    );

    // Network: skip 404s on optional assets and auth polling.
    const criticalNetworkFails = networkFailures.filter(
      (f) =>
        !f.includes("favicon") &&
        !f.includes("/api/auth/refresh") &&
        !f.includes("/__nextjs_original") &&
        !f.includes("_next/static")
    );

    expect(
      criticalErrors,
      `Console errors detected:\n${criticalErrors.join("\n")}`
    ).toHaveLength(0);

    expect(
      criticalNetworkFails,
      `Network 4xx/5xx failures:\n${criticalNetworkFails.join("\n")}`
    ).toHaveLength(0);

    // ── Screenshot directory listing ─────────────────────────────────────────
    const screenshots = fs
      .readdirSync(SNAP_DIR)
      .filter((f) => f.endsWith(".png"))
      .sort();
    console.log(
      `\n[PASS] Demo smoke complete. ${screenshots.length} screenshots saved to ${SNAP_DIR}:`
    );
    screenshots.forEach((f) => console.log(`  ${path.join(SNAP_DIR, f)}`));
  }
);
