import { type Page } from "@playwright/test";

export const LOCAL_BASE_URL = "http://localhost:3444";
export const ADMIN_EMAIL = "admin@raf.health";
export const ADMIN_PASSWORD = "Admin@123";

/**
 * Log in as the canonical admin user and wait for an authenticated page to load.
 * Retries once if the first attempt lands back on /login (e.g. timing race).
 */
export async function loginAsAdmin(page: Page): Promise<void> {
  await page.goto(`${LOCAL_BASE_URL}/login`);
  await page.waitForSelector('input[type="email"]', { state: "visible" });
  await page.fill('input[type="email"]', ADMIN_EMAIL);
  await page.fill('input[type="password"]', ADMIN_PASSWORD);
  await page.click('button[type="submit"]');
  // Wait until we leave /login (dashboard may redirect to any authenticated path)
  await page.waitForURL((url) => !url.pathname.startsWith("/login"), { timeout: 30_000 });
  await page.waitForLoadState("networkidle");
  // Guard: if we somehow landed back on login, try once more
  if (page.url().includes("/login")) {
    await page.fill('input[type="email"]', ADMIN_EMAIL);
    await page.fill('input[type="password"]', ADMIN_PASSWORD);
    await page.click('button[type="submit"]');
    await page.waitForURL((url) => !url.pathname.startsWith("/login"), { timeout: 30_000 });
    await page.waitForLoadState("networkidle");
  }
}

/**
 * Hide volatile elements (timestamps, live indicators, animations) so
 * screenshots are deterministic across runs.
 */
export async function hideVolatileElements(page: Page): Promise<void> {
  await page.evaluate(() => {
    const selectors = [
      '[data-testid="timestamp"]',
      '[data-testid="live-indicator"]',
      '[data-testid="auto-sync-toast"]',
      ".animate-pulse",
      ".animate-spin",
      "[data-volatile]",
      'time[datetime]',
    ];
    for (const sel of selectors) {
      document.querySelectorAll(sel).forEach((el) => {
        (el as HTMLElement).style.visibility = "hidden";
      });
    }
  });
}
