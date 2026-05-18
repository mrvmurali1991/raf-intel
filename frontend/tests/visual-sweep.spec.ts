/**
 * Visual regression sweep: 11 pages × 2 viewports × 2 themes = 44 screenshots
 * Pages: /, /worklist, /recapture, /suspects, /patients, /patients/[pid],
 *        /v28-impact, /radv, /audit, /goals, /reports
 */
import { test, Page } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";

const BASE_URL = "https://raf.comercioit.com";
const OUTPUT_DIR = "/tmp/visual-pass";

const PAGES = [
  { name: "dashboard", path: "/" },
  { name: "worklist", path: "/worklist" },
  { name: "recapture", path: "/recapture" },
  { name: "suspects", path: "/suspects" },
  { name: "patients", path: "/patients" },
  { name: "patient-detail", path: "FIRST_PID" }, // replaced at runtime
  { name: "v28-impact", path: "/v28-impact" },
  { name: "radv", path: "/radv" },
  { name: "audit", path: "/audit" },
  { name: "goals", path: "/goals" },
  { name: "reports", path: "/reports" },
];

const VIEWPORTS = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "mobile", width: 768, height: 1024 },
];

const THEMES = ["light", "dark"] as const;

// Ensure output dir exists
if (!fs.existsSync(OUTPUT_DIR)) {
  fs.mkdirSync(OUTPUT_DIR, { recursive: true });
}

async function login(page: Page) {
  await page.goto(`${BASE_URL}/login`, { waitUntil: "domcontentloaded", timeout: 30000 });
  // Wait for login form to appear
  await page.waitForSelector('input[type="email"], input[name="email"]', { timeout: 15000 });
  await page.fill('input[type="email"], input[name="email"]', "admin@raf.health");
  await page.fill('input[type="password"], input[name="password"]', "Admin@123");
  await page.click('button[type="submit"]');
  // Wait for redirect away from login
  await page.waitForFunction(
    () => !window.location.pathname.includes("/login"),
    { timeout: 30000 }
  );
  // Wait for auth to fully resolve (spinner gone, main content visible)
  await waitForAuthReady(page);
}

/**
 * Wait until the auth loading spinner is completely gone and main content is present.
 * The auth-layout shows a full-page spinner with aria-busy="true" while isLoading=true.
 */
async function waitForAuthReady(page: Page, timeout = 20000) {
  // Wait for aria-busy spinner to disappear completely
  await page.waitForFunction(
    () => {
      const busy = document.querySelectorAll('[aria-busy="true"]');
      const spinners = document.querySelectorAll('.animate-spin');
      return busy.length === 0 && spinners.length === 0;
    },
    { timeout }
  ).catch(() => {});

  // Ensure main content or sidebar is present
  await page.waitForSelector(
    '#main-content, [data-testid="sidebar"], nav[aria-label]',
    { timeout: 10000 }
  ).catch(() => {});

  // Small buffer for React render to settle
  await page.waitForTimeout(800);
}

/**
 * Apply theme by manipulating localStorage AND the DOM class, then
 * dispatching a StorageEvent so the same-tab useSyncExternalStore fires.
 * After that, wait for the dark/light class to be confirmed on <html>.
 */
async function applyTheme(page: Page, theme: "light" | "dark") {
  await page.evaluate((t) => {
    localStorage.setItem("raf-theme", t);
    const root = document.documentElement;
    if (t === "dark") {
      root.classList.add("dark");
      root.classList.remove("light");
    } else {
      root.classList.remove("dark");
      root.classList.add("light");
    }
    // Dispatch a storage event so same-tab listeners fire (useSyncExternalStore)
    window.dispatchEvent(new StorageEvent("storage", {
      key: "raf-theme",
      newValue: t,
      storageArea: window.localStorage,
    }));
  }, theme);

  // Wait for the class to actually be applied on <html>
  if (theme === "dark") {
    await page.waitForFunction(
      () => document.documentElement.classList.contains("dark"),
      { timeout: 5000 }
    ).catch(() => {});
  } else {
    await page.waitForFunction(
      () => !document.documentElement.classList.contains("dark"),
      { timeout: 5000 }
    ).catch(() => {});
  }

  // Allow React to re-render with new theme
  await page.waitForTimeout(500);
}

// Pages that make heavy API calls and need extra wait time
const SLOW_PAGES = new Set(["/reports", "/v28-impact", "/goals", "/worklist", "/recapture"]);

async function navigateTo(page: Page, url: string) {
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 30000 });
  // Wait for auth loading spinner to fully clear before any other waits
  await waitForAuthReady(page);

  // Determine extra wait time based on page
  const pathname = new URL(url).pathname;
  const extraWait = SLOW_PAGES.has(pathname) ? 6000 : 3000;

  // Additional wait for data to load (API responses, charts etc.)
  await page.waitForTimeout(extraWait);
}

async function getFirstPatientId(page: Page): Promise<string | null> {
  // Try to extract from the patients list page DOM
  try {
    // Navigate and wait for auth + data to load
    await navigateTo(page, `${BASE_URL}/patients`);
    // Wait for patient rows to appear
    await page.waitForSelector('a[href^="/patients/"]', { timeout: 15000 }).catch(() => {});
    // Look for patient links in the table
    const patientLink = await page.locator(
      'a[href^="/patients/"]'
    ).first().getAttribute("href");
    if (patientLink) {
      const pid = patientLink.replace("/patients/", "").split("?")[0].split("#")[0];
      if (pid && pid !== "" && !isNaN(Number(pid))) {
        return pid;
      }
    }
  } catch {
    // ignore
  }
  return null;
}

async function screenshotPage(
  page: Page,
  name: string,
  viewport: { name: string; width: number; height: number },
  theme: "light" | "dark"
) {
  const filename = `${name}__${viewport.name}__${theme}.png`;
  const filepath = path.join(OUTPUT_DIR, filename);
  await page.screenshot({ path: filepath, fullPage: true });
  console.log(`  Saved: ${filename}`);
  return filepath;
}

test.describe("Visual regression sweep @smoke @full", () => {
  let firstPid: string | null = null;

  test.beforeAll(async ({ browser }) => {
    // Use desktop viewport for PID extraction to ensure patients page loads correctly
    const ctx = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      ignoreHTTPSErrors: true,
    });
    const page = await ctx.newPage();
    await login(page);
    // Ensure light theme for PID extraction
    await applyTheme(page, "light");
    firstPid = await getFirstPatientId(page);
    console.log(`  First patient ID: ${firstPid}`);
    await page.close();
    await ctx.close();
  });

  for (const viewport of VIEWPORTS) {
    for (const theme of THEMES) {
      test(`Sweep ${viewport.name} ${theme} @smoke`, async ({ browser }) => {
        const ctx = await browser.newContext({
          viewport: { width: viewport.width, height: viewport.height },
          ignoreHTTPSErrors: true,
        });
        const page = await ctx.newPage();

        // Login and wait for auth to fully resolve
        await login(page);

        // Set theme AFTER login and auth is resolved
        await applyTheme(page, theme);

        // Navigate to dashboard first to ensure app state is initialized
        await navigateTo(page, `${BASE_URL}/`);
        // Re-apply theme after navigation (next.js navigation may reset DOM)
        await applyTheme(page, theme);

        for (const pg of PAGES) {
          let pagePath = pg.path;
          if (pagePath === "FIRST_PID") {
            if (firstPid) {
              pagePath = `/patients/${firstPid}`;
            } else {
              console.log("  Skipping patient-detail (no PID found)");
              continue;
            }
          }

          console.log(`Navigating to ${pagePath} [${viewport.name}, ${theme}]`);

          try {
            await navigateTo(page, `${BASE_URL}${pagePath}`);

            // Re-apply theme after each navigation to ensure dark class persists
            await applyTheme(page, theme);

            // Wait for auth spinner to be completely gone
            await waitForAuthReady(page, 15000);

            // Wait for data-loading spinners to clear (not counting auth ones)
            await page.waitForFunction(
              () => {
                // Only count non-full-page spinners (data loading, not auth)
                const spinners = document.querySelectorAll('.animate-spin');
                return spinners.length === 0;
              },
              { timeout: 10000 }
            ).catch(() => {});

            // Final settle time
            await page.waitForTimeout(1000);

            await screenshotPage(page, pg.name, viewport, theme);
          } catch (err) {
            console.error(`  ERROR on ${pagePath}: ${err}`);
            try {
              await screenshotPage(page, `${pg.name}__ERROR`, viewport, theme);
            } catch {}
          }
        }

        await ctx.close();
      });
    }
  }
});
