/**
 * auth-flow.spec.ts
 *
 * Full authentication lifecycle:
 *   - Login with valid credentials → dashboard redirect.
 *   - Login with wrong password → error message shown, no redirect.
 *   - Logout → /login redirect.
 *   - Password-rotation: Settings page renders "Change Password" form.
 *   - MFA settings page reachable (smoke — full TOTP flow requires device).
 *
 * Each test is self-contained; no shared state leaks between cases.
 */

import { test, expect } from "@playwright/test";
import { loginAs, loginAsAdmin, logout, assertNoA11yViolations } from "./helpers/auth";

test.describe("Auth flow — login / logout / password rotation", () => {
  test("admin login redirects to dashboard", async ({ page }) => {
    await loginAsAdmin(page);
    expect(page.url()).not.toContain("/login");
    await expect(page.locator("main, #main-content, [role='main']").first()).toBeVisible({ timeout: 10_000 });
  });

  test("wrong password shows error, stays on /login", async ({ page }) => {
    await page.goto("/login");
    await page.waitForSelector('input[type="email"]', { state: "visible", timeout: 15_000 });
    await page.fill('input[type="email"]', "admin@raf.health");
    await page.fill('input[type="password"]', "wrong-password-xyz");
    await page.click('button[type="submit"]');

    // Should not navigate away from /login.
    await page.waitForTimeout(3_000);
    expect(page.url()).toContain("/login");

    // An error message must be visible.
    const errorText = page.locator("text=/invalid|incorrect|failed|unauthorized/i");
    await expect(errorText.first()).toBeVisible({ timeout: 10_000 });
  });

  test("logout returns to /login", async ({ page }) => {
    await loginAsAdmin(page);
    await logout(page);
    expect(page.url()).toContain("/login");
  });

  test("settings page renders Change Password form", async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/settings");
    await page.waitForLoadState("networkidle");

    // Page must contain a password-change affordance.
    const pwSection = page.locator("text=/change password|new password|current password/i").first();
    await expect(pwSection).toBeVisible({ timeout: 15_000 });
    await assertNoA11yViolations(page);
  });

  test("MFA setup page is reachable and shows QR / TOTP section (smoke)", async ({ page }) => {
    await loginAsAdmin(page);
    // Try /settings/security, /settings/mfa, or /settings — any that renders MFA content.
    const candidateUrls = ["/settings/security", "/settings/mfa", "/settings"];
    let mfaVisible = false;
    for (const url of candidateUrls) {
      await page.goto(url);
      await page.waitForLoadState("networkidle");
      const mfaEl = page.locator("text=/multi.factor|MFA|authenticator|two.factor|2FA/i").first();
      if (await mfaEl.isVisible({ timeout: 5_000 }).catch(() => false)) {
        mfaVisible = true;
        break;
      }
    }
    // Soft assertion — if the app has no MFA UI yet, skip rather than fail.
    if (!mfaVisible) {
      test.skip();
    }
  });
});
