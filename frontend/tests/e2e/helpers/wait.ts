/**
 * wait.ts — Network / DOM polling helpers for E2E tests.
 *
 * Exports:
 *   waitForApiCall(page, urlPattern, statusCode?)
 *   waitForToast(page, textPattern?)
 *   waitForDrawer(page)
 */

import { type Page, type Response } from "@playwright/test";

/**
 * Returns a Promise that resolves with the matching Response once a network
 * request whose URL matches `urlPattern` completes with `expectedStatus`.
 *
 * Set `expectedStatus` to null to accept any status code.
 */
export async function waitForApiCall(
  page: Page,
  urlPattern: string | RegExp,
  expectedStatus: number | null = 200,
  timeoutMs = 30_000
): Promise<Response> {
  return page.waitForResponse(
    (resp) => {
      const matches =
        typeof urlPattern === "string"
          ? resp.url().includes(urlPattern)
          : urlPattern.test(resp.url());
      const statusOk =
        expectedStatus === null || resp.status() === expectedStatus;
      return matches && statusOk;
    },
    { timeout: timeoutMs }
  );
}

/**
 * Wait for any visible toast / snackbar notification.
 * Optionally assert that its text matches `textPattern`.
 */
export async function waitForToast(
  page: Page,
  textPattern?: string | RegExp,
  timeoutMs = 15_000
): Promise<void> {
  const toastSelectors = [
    "[role='status']",
    "[role='alert']",
    "[data-testid*='toast']",
    "[class*='toast']",
    "[class*='snackbar']",
    "[class*='notification']",
  ].join(", ");

  const toast = page.locator(toastSelectors).first();
  await toast.waitFor({ state: "visible", timeout: timeoutMs });

  if (textPattern) {
    const text = await toast.textContent();
    const matched =
      typeof textPattern === "string"
        ? text?.includes(textPattern)
        : textPattern.test(text ?? "");
    if (!matched) {
      throw new Error(`Toast text "${text}" did not match pattern ${textPattern}`);
    }
  }
}

/**
 * Wait for a slide-over drawer or panel to appear.
 * Returns the locator once visible.
 */
export async function waitForDrawer(page: Page, timeoutMs = 15_000) {
  const drawerSelectors = [
    "[role='dialog']",
    "[data-testid*='drawer']",
    "[class*='drawer']",
    "[class*='slide-over']",
    "[class*='side-panel']",
  ].join(", ");

  const drawer = page.locator(drawerSelectors).first();
  await drawer.waitFor({ state: "visible", timeout: timeoutMs });
  return drawer;
}
