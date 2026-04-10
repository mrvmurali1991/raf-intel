import { test, expect } from "@playwright/test";
import { login, logout, ADMIN_EMAIL, ADMIN_PASSWORD } from "./helpers";

/**
 * Authentication tests
 *
 * Covers the full auth lifecycle: successful login, error states, session
 * persistence, redirect guards, and logout.
 */
test.describe("Authentication", () => {
  // ---------------------------------------------------------------------------
  // Successful login
  // ---------------------------------------------------------------------------

  test("logs in with valid credentials and lands on the dashboard", async ({ page }) => {
    await page.goto("/login");

    // The login panel should be visible before submitting.
    await expect(page.getByRole("heading", { name: "Welcome Back" })).toBeVisible();

    await page.fill('input[type="email"]', ADMIN_EMAIL);
    await page.fill('input[type="password"]', ADMIN_PASSWORD);
    await page.click('button[type="submit"]');

    // After a successful login the app redirects to the dashboard root.
    await page.waitForURL("/", { timeout: 30_000 });
    expect(page.url()).toMatch(/\/$/);
  });

  // ---------------------------------------------------------------------------
  // Wrong password
  // ---------------------------------------------------------------------------

  test("shows an error when the password is wrong", async ({ page }) => {
    await page.goto("/login");
    await page.waitForSelector('input[type="email"]', { state: "visible" });

    await page.fill('input[type="email"]', ADMIN_EMAIL);
    await page.fill('input[type="password"]', "wrong-password-xyz");
    await page.click('button[type="submit"]');

    // An error alert should appear without navigating away from /login.
    const alert = page.getByRole("alert");
    await expect(alert).toBeVisible({ timeout: 15_000 });

    // Must still be on the login page.
    expect(page.url()).toContain("/login");
  });

  // ---------------------------------------------------------------------------
  // Unauthenticated redirect
  // ---------------------------------------------------------------------------

  test("redirects to /login when accessing a protected page without a session", async ({
    page,
  }) => {
    // Clear any stored session tokens before attempting to visit the dashboard.
    await page.goto("/login");
    await page.evaluate(() => {
      sessionStorage.clear();
      localStorage.clear();
    });

    await page.goto("/");
    // The AuthLayout should redirect unauthenticated visitors to /login.
    await page.waitForURL(/\/login/, { timeout: 15_000 });
    expect(page.url()).toContain("/login");
  });

  // ---------------------------------------------------------------------------
  // Logout
  // ---------------------------------------------------------------------------

  test("logs out and redirects to the login page", async ({ page }) => {
    await login(page);

    // Confirm we are on the dashboard.
    await page.waitForURL("/", { timeout: 30_000 });

    await logout(page);

    await expect(page.getByRole("heading", { name: "Welcome Back" })).toBeVisible();
  });

  // ---------------------------------------------------------------------------
  // Session persistence
  // ---------------------------------------------------------------------------

  test("session persists when navigating between pages", async ({ page }) => {
    await login(page);

    // Navigate away and come back — the user should remain authenticated.
    await page.goto("/patients");
    await page.waitForLoadState("networkidle");
    // Should NOT have been redirected to login.
    expect(page.url()).not.toContain("/login");

    await page.goto("/reports");
    await page.waitForLoadState("networkidle");
    expect(page.url()).not.toContain("/login");

    // Return to the dashboard.
    await page.goto("/");
    await page.waitForLoadState("networkidle");
    expect(page.url()).not.toContain("/login");
  });

  // ---------------------------------------------------------------------------
  // Login page elements
  // ---------------------------------------------------------------------------

  test("login page renders the HIPAA / SOC 2 trust badges", async ({ page }) => {
    await page.goto("/login");
    // The trust line is only visible on larger viewports (lg breakpoint).
    await page.setViewportSize({ width: 1440, height: 900 });
    await expect(page.getByText("HIPAA Compliant")).toBeVisible();
    await expect(page.getByText("SOC 2 Certified")).toBeVisible();
  });

  test("password visibility toggle works", async ({ page }) => {
    await page.goto("/login");
    await page.waitForSelector('input[type="password"]', { state: "visible" });

    const passwordInput = page.locator('input[id="password"]');
    await expect(passwordInput).toHaveAttribute("type", "password");

    // Click the show/hide toggle.
    await page.click('[aria-label="Show password"]');
    await expect(passwordInput).toHaveAttribute("type", "text");

    // Toggle back.
    await page.click('[aria-label="Hide password"]');
    await expect(passwordInput).toHaveAttribute("type", "password");
  });
});
