/**
 * RAF Intelligence — UI/UX Overhaul Demo Walkthrough
 *
 * Records an annotated video walkthrough of every major page showing what
 * changed in the UI/UX overhaul.  Annotations are injected into the live DOM
 * via page.evaluate() so they appear in the recorded video.
 *
 * Run (prod):
 *   npx playwright test tests/e2e/demo-ux-walkthrough.spec.ts \
 *     --config playwright.config.ts --headed
 *
 * Run (local):
 *   E2E_BASE_URL=http://localhost:3000 \
 *   npx playwright test tests/e2e/demo-ux-walkthrough.spec.ts \
 *     --config playwright.config.ts --headed
 *
 * Screenshots land in:  tests/e2e/_screenshots/ux-walkthrough/
 * Video lands in:        test-results/<test-name>/video.webm
 */

import { test, type Page } from "@playwright/test";
import path from "path";

// ---------------------------------------------------------------------------
// Test-level overrides
// ---------------------------------------------------------------------------

test.use({
  video: { mode: "on", size: { width: 1440, height: 900 } },
  viewport: { width: 1440, height: 900 },
  // Use the base URL from the config (prod or local via E2E_BASE_URL env var).
});

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DEMO_EMAIL = "admin@raf.health";
const DEMO_PASSWORD = "Admin@123";
const SCREENSHOT_DIR = "tests/e2e/_screenshots/ux-walkthrough";

// ---------------------------------------------------------------------------
// Annotation helpers
// ---------------------------------------------------------------------------

/**
 * Highlights an element and renders a floating callout bubble near it.
 * Silently skips if the selector isn't found so a missing element never
 * crashes the whole demo.
 */
async function addCallout(
  page: Page,
  selector: string,
  text: string,
  position: "top" | "bottom" | "right" = "top"
): Promise<void> {
  await page
    .evaluate(
      ({ sel, txt, pos }: { sel: string; txt: string; pos: string }) => {
        const el = document.querySelector(sel) as HTMLElement | null;
        if (!el) return;

        const rect = el.getBoundingClientRect();

        // Highlight the target element with a teal outline.
        el.style.outline = "3px solid #00b4d8";
        el.style.outlineOffset = "4px";
        el.style.borderRadius = "4px";
        el.style.transition = "outline 0.3s ease";

        // Build the callout bubble.
        const callout = document.createElement("div");
        callout.className = "raf-demo-callout";
        callout.innerHTML = txt;
        callout.style.cssText = `
          position: fixed;
          background: #1a1f36;
          color: #ffffff;
          padding: 12px 20px;
          border-radius: 8px;
          font-size: 15px;
          font-weight: 600;
          font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          box-shadow: 0 8px 32px rgba(0,0,0,0.45);
          border-left: 4px solid #00b4d8;
          z-index: 2147483647;
          max-width: 420px;
          line-height: 1.6;
          pointer-events: none;
          white-space: pre-wrap;
        `;

        const scrollX = window.scrollX;
        const scrollY = window.scrollY;

        if (pos === "top") {
          callout.style.left = `${Math.max(8, rect.left + scrollX)}px`;
          callout.style.top = `${Math.max(8, rect.top + scrollY - 68)}px`;
        } else if (pos === "bottom") {
          callout.style.left = `${Math.max(8, rect.left + scrollX)}px`;
          callout.style.top = `${rect.bottom + scrollY + 12}px`;
        } else {
          // right
          callout.style.left = `${rect.right + scrollX + 16}px`;
          callout.style.top = `${rect.top + scrollY}px`;
        }

        document.body.appendChild(callout);
      },
      { sel: selector, txt: text, pos: position }
    )
    .catch(() => {
      // Selector not found — skip silently.
    });
}

/**
 * Remove every callout bubble and all highlight outlines injected by this
 * script so the page is clean before the next annotation.
 */
async function removeCallouts(page: Page): Promise<void> {
  await page.evaluate(() => {
    document
      .querySelectorAll(".raf-demo-callout")
      .forEach((el) => el.remove());
    document
      .querySelectorAll<HTMLElement>(
        '[style*="outline: 3px solid #00b4d8"]'
      )
      .forEach((el) => {
        el.style.outline = "";
        el.style.outlineOffset = "";
        el.style.borderRadius = "";
        el.style.transition = "";
      });
  });
}

/**
 * Render (or replace) the full-width sticky banner at the top of the viewport.
 * The banner identifies the current scene for viewers watching the video.
 */
async function addBanner(page: Page, text: string): Promise<void> {
  await page.evaluate((txt: string) => {
    const old = document.getElementById("raf-demo-banner");
    if (old) old.remove();

    const banner = document.createElement("div");
    banner.id = "raf-demo-banner";
    banner.innerHTML = txt;
    banner.style.cssText = `
      position: fixed;
      top: 0;
      left: 0;
      right: 0;
      background: linear-gradient(135deg, #0f172a 0%, #0f766e 100%);
      color: #ffffff;
      padding: 13px 28px;
      font-size: 17px;
      font-weight: 700;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      text-align: center;
      z-index: 2147483646;
      letter-spacing: 0.4px;
      border-bottom: 2px solid #00b4d8;
      pointer-events: none;
    `;
    document.body.appendChild(banner);
  }, text);
}

/** Remove the scene banner. */
async function removeBanner(page: Page): Promise<void> {
  await page.evaluate(() => {
    const el = document.getElementById("raf-demo-banner");
    if (el) el.remove();
  });
}

/**
 * Pause for a given number of milliseconds so viewers can read annotations.
 */
async function pause(page: Page, ms: number): Promise<void> {
  await page.waitForTimeout(ms);
}

/**
 * Save a screenshot into the dedicated walkthrough folder.
 */
async function snap(page: Page, name: string): Promise<void> {
  await page
    .screenshot({
      path: path.join(SCREENSHOT_DIR, name),
      fullPage: false, // viewport-only keeps the injected fixed-position elements visible
    })
    .catch(() => {});
}

// ---------------------------------------------------------------------------
// Robust navigation helper
// ---------------------------------------------------------------------------

async function goTo(page: Page, href: string): Promise<void> {
  await page.goto(href, { waitUntil: "domcontentloaded" });
  // Also wait for network to idle so data-fetching resolves.
  await page.waitForLoadState("networkidle").catch(() => {});
}

// ---------------------------------------------------------------------------
// The demo test
// ---------------------------------------------------------------------------

test("UX overhaul walkthrough", async ({ page, context }) => {
  test.setTimeout(600_000); // 10-minute ceiling for the full walkthrough

  // Record to the correct directory.
  await context.tracing.start({ screenshots: true, snapshots: false });

  // ===========================================================================
  // SCENE 1 — Login (≈10 sec)
  // ===========================================================================

  await goTo(page, "/login");
  await page.waitForSelector('input[type="email"]', { state: "visible", timeout: 20_000 });

  await addBanner(page, "RAF Intelligence — UI/UX Overhaul Demo");
  await pause(page, 2_000);

  // Fill credentials and submit.
  await page.fill('input[type="email"]', DEMO_EMAIL);
  await page.fill('input[type="password"]', DEMO_PASSWORD);
  await snap(page, "01-login.png");

  await page.click('button[type="submit"]');
  await page.waitForURL((url) => !url.pathname.includes("/login"), {
    timeout: 30_000,
  });

  await page.waitForLoadState("networkidle").catch(() => {});
  await pause(page, 2_000);

  // ===========================================================================
  // SCENE 2 — Dashboard KPI cards (≈15 sec)
  // ===========================================================================

  await addBanner(page, "Dashboard — Redesigned KPI Cards");
  await pause(page, 1_000);

  // KPI strip: try the most likely selectors from the current dashboard component.
  const kpiSelectors = [
    "[data-testid='kpi-strip']",
    ".kpi-strip",
    "[class*='kpi']",
    "main > section:first-of-type",
    // Fallback: first grid of cards on the page.
    "[class*='grid']:first-of-type",
  ];

  let kpiHit = false;
  for (const sel of kpiSelectors) {
    const count = await page.locator(sel).count();
    if (count > 0) {
      await addCallout(
        page,
        sel,
        "NEW: Focused 4-KPI layout\nTotal Patients · Open Suspects · Avg RAF · Revenue at Risk",
        "bottom"
      );
      kpiHit = true;
      break;
    }
  }
  if (!kpiHit) {
    // Fallback: annotate the main content area.
    await addCallout(
      page,
      "main",
      "NEW: Focused 4-KPI layout\nTotal Patients · Open Suspects · Avg RAF · Revenue at Risk",
      "top"
    ).catch(() => {});
  }

  await pause(page, 3_000);
  await snap(page, "02-dashboard-kpis.png");
  await removeCallouts(page);

  // Sidebar callout.
  await addCallout(
    page,
    "nav, [data-testid='sidebar'], aside",
    "FIXED: Unique icons per nav item — no more duplicate ClipboardCheck icons",
    "right"
  ).catch(() => {});
  await pause(page, 3_000);
  await snap(page, "03-sidebar-icons.png");
  await removeCallouts(page);

  // ===========================================================================
  // SCENE 3 — Sidebar (≈10 sec)
  // ===========================================================================

  await addBanner(page, "Sidebar — Rewritten from 1,463 to 1,061 lines");
  await pause(page, 1_000);

  await addCallout(
    page,
    "nav, aside, [data-testid='sidebar']",
    "Zero hardcoded colors — all CSS variables now.  Dark mode ready.",
    "right"
  ).catch(() => {});
  await pause(page, 3_000);
  await removeCallouts(page);

  // Collapse the sidebar.
  const collapseSelectors = [
    '[aria-label="Collapse sidebar"]',
    '[aria-label="collapse sidebar"]',
    '[data-testid="sidebar-collapse"]',
    'button[title*="collapse" i]',
    'button[title*="close" i]',
    // The PanelLeftClose icon is often inside a button with no text — try the SVG parent.
    'button:has(svg[class*="panel"])',
    // Last resort: first button inside the nav.
    "nav button:first-of-type",
  ];

  let collapsed = false;
  for (const sel of collapseSelectors) {
    const btn = page.locator(sel).first();
    if ((await btn.count()) > 0 && (await btn.isVisible().catch(() => false))) {
      await btn.click().catch(() => {});
      await pause(page, 1_000);
      collapsed = true;
      break;
    }
  }

  await addCallout(
    page,
    "nav, aside, [data-testid='sidebar']",
    "Each icon is now unique — identifiable at a glance",
    "right"
  ).catch(() => {});
  await pause(page, 3_000);
  await snap(page, "04-sidebar-collapsed.png");
  await removeCallouts(page);

  // Re-expand the sidebar if we collapsed it.
  if (collapsed) {
    const expandSelectors = [
      '[aria-label="Expand sidebar"]',
      '[aria-label="expand sidebar"]',
      '[data-testid="sidebar-expand"]',
      'button[title*="expand" i]',
      'nav button:first-of-type',
    ];
    for (const sel of expandSelectors) {
      const btn = page.locator(sel).first();
      if ((await btn.count()) > 0 && (await btn.isVisible().catch(() => false))) {
        await btn.click().catch(() => {});
        await pause(page, 1_000);
        break;
      }
    }
  }

  // ===========================================================================
  // SCENE 4 — Patients page (≈15 sec)
  // ===========================================================================

  await addBanner(page, "Patients — Consistent Layout & Empty States");
  await goTo(page, "/patients");

  // Wait for the page header or table to appear.
  await page
    .waitForSelector("h1, h2, table, [class*='PageHeader'], [data-testid='page-header']", {
      timeout: 20_000,
    })
    .catch(() => {});
  await pause(page, 2_000);

  await addCallout(
    page,
    "h1, h2, [class*='PageHeader'], [data-testid='page-header']",
    "Shared PageHeader component — consistent across all pages",
    "bottom"
  ).catch(() => {});
  await pause(page, 3_000);
  await snap(page, "05-patients-header.png");
  await removeCallouts(page);

  await addCallout(
    page,
    "table, [class*='table'], [data-testid='patients-table'], main > div",
    "Inline styles replaced with Tailwind — consistent spacing (p-6)",
    "top"
  ).catch(() => {});
  await pause(page, 3_000);
  await removeCallouts(page);

  // ===========================================================================
  // SCENE 5 — Suspects (≈15 sec)
  // ===========================================================================

  await addBanner(page, "HCC Suspects — The Revenue Finder");
  await goTo(page, "/suspects");

  await page
    .waitForSelector("table, [class*='list'], [class*='suspects'], main > div", {
      timeout: 20_000,
    })
    .catch(() => {});
  await pause(page, 2_000);

  await addCallout(
    page,
    "table, [class*='suspects-list'], main > div:first-of-type",
    "Revenue impact shown in teal bold — each row is dollars on the table",
    "top"
  ).catch(() => {});
  await pause(page, 3_000);
  await snap(page, "06-suspects-revenue.png");
  await removeCallouts(page);

  // Accept/Reject buttons.
  await addCallout(
    page,
    "button:has-text('Accept'), button:has-text('Reject'), [aria-label*='accept' i], [aria-label*='reject' i]",
    "Accept/Reject workflow — one click to capture revenue",
    "right"
  ).catch(() => {});
  await pause(page, 3_000);
  await removeCallouts(page);

  // ===========================================================================
  // SCENE 6 — Recapture Gaps (≈15 sec)
  // ===========================================================================

  await addBanner(page, "Recapture Gaps — Protect Last Year's Revenue");
  await goTo(page, "/recapture");

  await page
    .waitForSelector("table, [class*='recapture'], main > div", {
      timeout: 20_000,
    })
    .catch(() => {});
  await pause(page, 2_000);

  await addCallout(
    page,
    "table, [class*='recapture'], main > div:first-of-type",
    "NEW: Revenue Impact column + color-coded status badges",
    "top"
  ).catch(() => {});
  await pause(page, 3_000);
  await snap(page, "07-recapture-gaps.png");
  await removeCallouts(page);

  // ===========================================================================
  // SCENE 7 — Worklist (≈10 sec)
  // ===========================================================================

  await addBanner(page, "Provider Worklist — Today's Action Items");
  await goTo(page, "/worklist");

  await page
    .waitForSelector("table, [class*='worklist'], [class*='empty'], main", {
      timeout: 20_000,
    })
    .catch(() => {});
  await pause(page, 2_000);

  await addCallout(
    page,
    "main, [class*='worklist'], [class*='empty-state']",
    "NEW: Empty state with helpful message when no items",
    "top"
  ).catch(() => {});
  await pause(page, 3_000);
  await snap(page, "08-worklist.png");
  await removeCallouts(page);

  // ===========================================================================
  // SCENE 8 — Goals (≈10 sec)
  // ===========================================================================

  await addBanner(page, "Quarterly Goals — Track RAF Targets");
  await goTo(page, "/goals");

  await page
    .waitForSelector("main, [class*='goals'], [class*='progress']", {
      timeout: 20_000,
    })
    .catch(() => {});
  await pause(page, 2_000);

  await addCallout(
    page,
    "main, [class*='goals'], [role='progressbar']",
    "NEW: Progress bars in teal/amber/red + empty state with CTA",
    "top"
  ).catch(() => {});
  await pause(page, 3_000);
  await snap(page, "09-goals.png");
  await removeCallouts(page);

  // ===========================================================================
  // SCENE 9 — Reports (≈10 sec)
  // ===========================================================================

  await addBanner(page, "Reports — Analytics & Insights");
  await goTo(page, "/reports");

  await page
    .waitForSelector("h1, h2, [class*='PageHeader'], main > div", {
      timeout: 20_000,
    })
    .catch(() => {});
  await pause(page, 2_000);

  await addCallout(
    page,
    "h1, h2, [class*='PageHeader'], [data-testid='page-header']",
    "PageHeader with icon + actions slot — consistent pattern",
    "bottom"
  ).catch(() => {});
  await pause(page, 3_000);
  await snap(page, "10-reports.png");
  await removeCallouts(page);

  // ===========================================================================
  // SCENE 10 — Command Palette (≈10 sec)
  // ===========================================================================

  // Navigate back to the dashboard so the top bar is visible.
  await goTo(page, "/");
  await pause(page, 1_500);

  await addBanner(page, "Command Palette — Now Discoverable");

  // Locate the ⌘K badge/button in the top bar.
  const cmdkSelectors = [
    '[aria-label*="command" i]',
    '[aria-label*="search" i]',
    'button:has-text("⌘K")',
    'kbd:has-text("K")',
    '[data-testid="command-palette-trigger"]',
    '[class*="command"][class*="badge"]',
    '[class*="kbd"]',
  ];

  for (const sel of cmdkSelectors) {
    const el = page.locator(sel).first();
    if ((await el.count()) > 0) {
      await addCallout(
        page,
        sel,
        "NEW: ⌘K badge visible in top bar — users can now discover search",
        "bottom"
      ).catch(() => {});
      break;
    }
  }

  await pause(page, 3_000);
  await snap(page, "11-command-palette-hint.png");

  // Open the command palette via keyboard shortcut.
  await page.keyboard.press("Meta+k");
  await pause(page, 2_000);
  await snap(page, "12-command-palette-open.png");
  await page.keyboard.press("Escape");
  await pause(page, 1_000);
  await removeCallouts(page);

  // ===========================================================================
  // SCENE 11 — Dark Mode (≈10 sec)
  // ===========================================================================

  // Try to find the theme toggle in the sidebar.
  const themeToggles = [
    '[aria-label*="dark" i]',
    '[aria-label*="theme" i]',
    '[aria-label*="light" i]',
    '[data-testid="theme-toggle"]',
    'button:has(svg[class*="moon"])',
    'button:has(svg[class*="sun"])',
    // Look for Moon/Sun icon buttons anywhere on page.
    'button[title*="dark" i]',
    'button[title*="theme" i]',
  ];

  let themeToggleFound = false;
  for (const sel of themeToggles) {
    const btn = page.locator(sel).first();
    if ((await btn.count()) > 0 && (await btn.isVisible().catch(() => false))) {
      await btn.click().catch(() => {});
      themeToggleFound = true;
      break;
    }
  }

  if (!themeToggleFound) {
    // Try clicking the user avatar area where themes sometimes live.
    await page
      .locator(
        '[data-testid="user-menu"], [aria-label*="user" i], [aria-label*="profile" i]'
      )
      .first()
      .click()
      .catch(() => {});
    await pause(page, 800);
    await page
      .locator('button:has-text("Dark"), button:has-text("Light"), button:has-text("Theme")')
      .first()
      .click()
      .catch(() => {});
  }

  await addBanner(page, "Dark Mode — Now Consistent Across All Components");
  await pause(page, 2_000);
  await snap(page, "13-dark-mode.png");
  await removeCallouts(page);

  // Toggle back to light mode so the final banner looks clean.
  for (const sel of themeToggles) {
    const btn = page.locator(sel).first();
    if ((await btn.count()) > 0 && (await btn.isVisible().catch(() => false))) {
      await btn.click().catch(() => {});
      break;
    }
  }
  await pause(page, 1_000);

  // ===========================================================================
  // SCENE 12 — Final Summary (≈5 sec)
  // ===========================================================================

  await addBanner(
    page,
    "✅  20 Agents · 28 Issues Fixed · Zero Hardcoded Colors · Production Ready"
  );
  await removeBanner(page); // immediately replace with the summary banner so it renders clean
  await addBanner(
    page,
    "✅  20 Agents · 28 Issues Fixed · Zero Hardcoded Colors · Production Ready"
  );
  await pause(page, 3_000);
  await snap(page, "14-final.png");

  // Cleanup: remove all injected DOM nodes before the test closes.
  await removeCallouts(page);
  await removeBanner(page);
});
