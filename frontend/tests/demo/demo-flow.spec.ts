/**
 * RAF Intelligence — sales / investor demo flow (v2).
 *
 * 7 narrative scenes, ~5–7 minutes at conversational pace.  Each scene:
 *   - prints a one-line talking point to the terminal so the presenter
 *     can read along
 *   - waits for the actual content the value-prop depends on (no
 *     ``waitForLoadState`` — React Query keeps the network busy so
 *     ``networkidle`` never fires reliably)
 *   - takes TWO screenshots: an unannotated full-page shot for the
 *     deck, and an annotated shot with a red highlight box around the
 *     specific tile / chip / banner the scene argues from
 *   - uses ``softAssertVisible`` to flag when a value-prop element is
 *     missing without aborting the run (so we always produce a
 *     storyboard for the presenter to review)
 *
 * Run examples
 * ------------
 *   # Headed live demo (1.5s pause between scenes)
 *   cd frontend && DEMO_PASSWORD='Admin@123' \
 *     npx playwright test --config=playwright.demo.config.ts --headed
 *
 *   # Slow-mo for live screen-share (3s dwell)
 *   DEMO_PAUSE_MS=3000 PWDEBUG_SLOWMO=400 \
 *     npx playwright test --config=playwright.demo.config.ts --headed
 *
 *   # Headless + recorded video
 *   DEMO_VIDEO=1 \
 *     npx playwright test --config=playwright.demo.config.ts
 *
 *   # Run a single scene (e.g. just rehearse Scene 4)
 *   npx playwright test --config=playwright.demo.config.ts -g "Scene 4"
 */
import { test } from "@playwright/test";
import {
  authResolved,
  narrate,
  status,
  shot,
  annotatedShot,
  waitForFirst,
  softAssertVisible,
  probeDataReadiness,
  logReadiness,
  ensureDir,
  SHOT_DIR,
  BASE_URL,
} from "./demo-helpers";

test.describe.configure({ mode: "serial" });

test.describe("RAF Intelligence — sales demo flow", () => {
  // Auth setup runs in ./global-setup.ts — see that file for why we
  // can't just login per-scene (rate-limit + access-token-in-memory).
  // beforeAll here is just a data-readiness banner; the storageState
  // is already in place when each scene's `page` fixture spawns.
  test.beforeAll(async ({ browser }) => {
    ensureDir(SHOT_DIR);
    const ctx = await browser.newContext({ storageState: undefined });
    const page = await ctx.newPage();
    const readiness = await probeDataReadiness(page);
    logReadiness(readiness);
    await ctx.close();
    if (
      !readiness.emr_connected ||
      (readiness.patients_total === 0 &&
        readiness.open_recapture_gaps === 0)
    ) {
      // eslint-disable-next-line no-console
      console.log(
        "\n  ⚠  Demo data is sparse.  The screenshots will capture\n" +
          "     onboarding / empty states for sparse-data scenes.  This\n" +
          "     is the correct UX behaviour — but for a deck-ready\n" +
          "     storyboard you want EMR connected + patient panel\n" +
          "     loaded.  Connect Demo EMR via /emr-config, then\n" +
          "     re-run this command.\n",
      );
    }
    // eslint-disable-next-line no-console
    console.log(`\n  Demo shots: ${SHOT_DIR}`);
    console.log(`  Target:     ${BASE_URL}\n`);
  });

  // -------------------------------------------------------------------------
  test("Scene 1 — Monday morning: Today's worklist", async ({ page }) => {
    narrate(
      "Scene 1",
      "A provider opens the app on Monday morning.  They don't want a generic dashboard — they want to know which patients to see this week and why.",
    );

    await page.goto(`${BASE_URL}/worklist`);

    if (!(await authResolved(page))) {
      status("auth-context never resolved — capturing what we have");
    }

    const matched = await waitForFirst(page, [
      "Today's worklist",
      "Patients to see",
      "patients prioritized",
      "You're caught up",
      "AI-Powered Risk Adjustment", // onboarding fallback
    ]);
    if (matched) {
      const txt = (await matched.textContent())?.trim() ?? "";
      status(`landed on: "${txt.slice(0, 60)}"`);
    } else {
      status("no expected content — page may be blank");
    }

    narrate(
      "Scene 1",
      "Today's worklist sorts patients by priority score (open gaps × revenue at risk).  Each card is mobile-friendly so the iPad in an exam room is a first-class device, not an afterthought.",
    );

    await shot(page, "01-worklist", { fullPage: true });
    await annotatedShot(page, "01-worklist", [
      page.getByText(/Patients to see/i),
      page.getByText(/Open gaps/i),
      page.getByText(/Today's worklist/i),
    ]);
  });

  // -------------------------------------------------------------------------
  test("Scene 2 — Why this HCC? KG explainability", async ({ page }) => {
    narrate(
      "Scene 2",
      "The differentiator vs Navina and Apixio: every suspect HCC has a traceable evidence chain.  Hover any HCC chip to see ICD-10 → SNOMED → HCC mapping with literature citations.",
    );

    await page.goto(`${BASE_URL}/recapture`);
    await waitForFirst(page, [
      "Recapture Gaps",
      "Total Gaps",
      "Most Common",
      "No data",
    ]);

    await shot(page, "02a-recapture-overview", { fullPage: true });

    // Hover a real HCC chip if any are rendered.
    const hccChip = page.getByRole("button", { name: /HCC \d/i }).first();
    if (await hccChip.count()) {
      await hccChip.scrollIntoViewIfNeeded();
      await hccChip.hover();
      await page.waitForTimeout(900);
      await shot(page, "02b-hcc-popover");
      await annotatedShot(page, "02b-hcc-popover", [
        page.getByRole("dialog"),
        page.getByText(/SNOMED|ICD-10|Why this/i),
        hccChip,
      ]);
      narrate(
        "Scene 2",
        "Auditors love this — RADV defense argues from documented evidence, not 'the model said so'.  Citations are the difference between getting paid and getting clawed back.",
      );
    } else {
      status("no HCC chips rendered — gaps table is empty");
    }
  });

  // -------------------------------------------------------------------------
  test("Scene 3 — Calibrated confidence", async ({ page }) => {
    narrate(
      "Scene 3",
      "Every confidence number is Platt-calibrated.  Raw ECE was 0.22 — when the model said 78%, the real-world rate was closer to 56%.  After Platt scaling, ECE drops to 0.03.  When you see 78% here, it means 78%.",
    );

    await page.goto(`${BASE_URL}/suspects`);
    await waitForFirst(page, [
      "Suspect",
      "Confidence",
      "Suspected Condition",
      "No suspects",
    ]);

    await shot(page, "03-suspects-overview", { fullPage: true });

    const calChip = page.getByText(/calibrated/i).first();
    await softAssertVisible(calChip, "calibrated-confidence chip");
    await annotatedShot(page, "03-suspects-calibrated", [
      page.getByText(/calibrated/i),
      page.getByText(/Confidence/i).first(),
    ]);
  });

  // -------------------------------------------------------------------------
  test("Scene 4 — Audit defense (RADV + Cohen's kappa)", async ({ page }) => {
    narrate(
      "Scene 4",
      "Dual-coder MEAT audit trail with Cohen's kappa for inter-rater reliability — not naïve proportion-agreement.  One-click PDF export of audit-ready gaps for CMS RADV submission.",
    );

    await page.goto(`${BASE_URL}/recapture`);
    await waitForFirst(page, ["Recapture", "RADV Audit Defense", "Audit Ready"]);

    const auditHeader = page
      .getByRole("heading", { name: /RADV Audit Defense|Audit Ready/i })
      .first();
    if (await auditHeader.count()) {
      await auditHeader.scrollIntoViewIfNeeded();
      await page.waitForTimeout(600);
    }

    await shot(page, "04-audit-readiness", { fullPage: false });

    // The IRR tile is the value-prop of this scene.
    const irrTile = page.getByText(/Inter-rater reliability/i).first();
    await softAssertVisible(irrTile, "inter-rater reliability tile (kappa)");
    await annotatedShot(page, "04-audit-readiness", [
      page.getByText(/Inter-rater reliability/i),
      page.getByText(/Audit Ready/i),
      auditHeader,
    ]);
  });

  // -------------------------------------------------------------------------
  test("Scene 5 — Velocity & decay", async ({ page }) => {
    narrate(
      "Scene 5",
      "Recapture velocity KPIs + decay curve.  Tells the operations team how fast gaps close month-over-month so they can intervene before the year-end cliff — most teams discover in November they're behind; we surface that gap in February.",
    );

    await page.goto(`${BASE_URL}/recapture`);
    await waitForFirst(page, ["Recapture", "Total Gaps"]);

    const velocityHeader = page
      .getByRole("heading", { name: /velocity|decay/i })
      .first();
    if (await velocityHeader.count()) {
      await velocityHeader.scrollIntoViewIfNeeded();
      await page.waitForTimeout(600);
    }

    await shot(page, "05-velocity-decay", { fullPage: false });
    await softAssertVisible(velocityHeader, "Recapture velocity & decay header");
    await annotatedShot(page, "05-velocity-decay", [
      page.getByText(/Avg Days to Close/i),
      page.getByText(/YE Projected/i),
      velocityHeader,
    ]);
  });

  // -------------------------------------------------------------------------
  test("Scene 6 — CFO executive summary", async ({ page }) => {
    narrate(
      "Scene 6",
      "CFO view: quarterly $ projection, top conditions by revenue, top providers, year-over-year.  The amber 'PROJECTED' badge tells the CFO at a glance what's actual vs forecast — the single most-asked question in the finance review.",
    );

    await page.goto(`${BASE_URL}/recapture`);
    await waitForFirst(page, ["Recapture", "Total Gaps"]);

    const cfoHeader = page
      .getByRole("heading", { name: /CFO executive summary|Projected/i })
      .first();
    if (await cfoHeader.count()) {
      await cfoHeader.scrollIntoViewIfNeeded();
      await page.waitForTimeout(600);
    }

    await shot(page, "06-cfo-summary", { fullPage: false });
    await softAssertVisible(cfoHeader, "CFO executive summary header");
    await annotatedShot(page, "06-cfo-summary", [
      page.getByText(/PROJECTED/),
      page.getByText(/Q1|Q2|Q3|Q4/i).first(),
      cfoHeader,
    ]);
  });

  // -------------------------------------------------------------------------
  test("Scene 7 — Mobile (iPad in the exam room)", async ({ page }) => {
    narrate(
      "Scene 7",
      "Same worklist, on a phone-sized viewport.  Auto-fit grid collapses to a single column on phone, two on tablet — providers chart at the bedside, not in front of a laptop.  KG popovers and audit defense work identically.",
    );


    // Phone (iPhone 13 Pro Max) — single column expected.
    await page.setViewportSize({ width: 414, height: 896 });
    await page.goto(`${BASE_URL}/worklist`);
    await waitForFirst(page, [
      "Today's worklist",
      "You're caught up",
      "AI-Powered Risk Adjustment",
    ]);
    await shot(page, "07a-worklist-phone", { fullPage: true });

    // Tablet (iPad portrait) — 2-column grid expected.
    await page.setViewportSize({ width: 768, height: 1024 });
    await page.reload();
    await waitForFirst(page, [
      "Today's worklist",
      "You're caught up",
      "AI-Powered Risk Adjustment",
    ]);
    await shot(page, "07b-worklist-tablet", { fullPage: true });

    // Reset to desktop so any subsequent debugging in --ui mode is normal.
    await page.setViewportSize({ width: 1440, height: 900 });
  });

  // -------------------------------------------------------------------------
  test.afterAll(() => {
    // eslint-disable-next-line no-console
    console.log(`\n  Demo run complete.  Storyboard: ${SHOT_DIR}\n`);
  });
});
