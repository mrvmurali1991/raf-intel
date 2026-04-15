/**
 * login.spec.ts
 *
 * E2E tests for the full login flow.
 *
 * Covers:
 * - Login page renders correctly
 * - Successful login redirects to dashboard
 * - Invalid credentials shows error message
 * - Empty form fields show validation errors
 * - Logout clears session and redirects to login
 */

import { test, expect } from "@playwright/test";

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || "http://localhost:3001";
const USERNAME = process.env.TEST_USERNAME || "admin@raf.health";
const PASSWORD = process.env.TEST_PASSWORD || "Admin@123";

// Login tests run WITHOUT the saved auth state (we're testing login itself)
test.use({ storageState: { cookies: [], origins: [] } });

test.describe("Login page", () => {
  test("login page renders the email and password fields", async ({ page }) => {
    await page.goto(`${BASE_URL}/login`);

    await expect(page.getByLabel(/email/i)).toBeVisible();
    await expect(page.getByLabel(/password/i)).toBeVisible();
    await expect(page.getByRole("button", { name: /sign in|login/i })).toBeVisible();
  });

  test("login page has correct title", async ({ page }) => {
    await page.goto(`${BASE_URL}/login`);
    await expect(page).toHaveTitle(/raf|intelligence|login/i);
  });

  test("successful login redirects to dashboard", async ({ page }) => {
    await page.goto(`${BASE_URL}/login`);

    await page.getByLabel(/email/i).fill(USERNAME);
    await page.getByLabel(/password/i).fill(PASSWORD);
    await page.getByRole("button", { name: /sign in|login/i }).click();

    // After login, we should NOT be on the login page
    await expect(page).not.toHaveURL(/\/login/, { timeout: 20_000 });
  });

  test("invalid credentials shows error message", async ({ page }) => {
    await page.goto(`${BASE_URL}/login`);

    await page.getByLabel(/email/i).fill("wrong@raf.health");
    await page.getByLabel(/password/i).fill("WrongPass999!");
    await page.getByRole("button", { name: /sign in|login/i }).click();

    // Error message should appear
    await expect(
      page.getByText(/invalid|incorrect|credentials|unauthorized/i)
    ).toBeVisible({ timeout: 10_000 });
  });

  test("empty email shows validation error", async ({ page }) => {
    await page.goto(`${BASE_URL}/login`);

    await page.getByLabel(/password/i).fill("Admin@123");
    await page.getByRole("button", { name: /sign in|login/i }).click();

    // Form should not submit — validation message or field required indicator
    await expect(page).toHaveURL(/\/login/);
  });

  test("empty password shows validation error", async ({ page }) => {
    await page.goto(`${BASE_URL}/login`);

    await page.getByLabel(/email/i).fill(USERNAME);
    await page.getByRole("button", { name: /sign in|login/i }).click();

    // Form should not submit
    await expect(page).toHaveURL(/\/login/);
  });
});

test.describe("Logout flow", () => {
  // This test starts with saved auth state
  test.use({
    storageState: ".auth/user.json",
  });

  test("logout redirects to login page", async ({ page }) => {
    // Navigate to the app (already authenticated)
    await page.goto(`${BASE_URL}/`);
    await expect(page).not.toHaveURL(/\/login/, { timeout: 10_000 });

    // Find and click the logout button (could be in a dropdown or nav)
    const logoutButton = page.getByRole("button", { name: /logout|sign out/i });
    if (await logoutButton.isVisible({ timeout: 3_000 }).catch(() => false)) {
      await logoutButton.click();
    } else {
      // Try opening a user menu first
      const userMenu = page.getByRole("button", { name: /user|account|profile|admin/i }).first();
      if (await userMenu.isVisible({ timeout: 3_000 }).catch(() => false)) {
        await userMenu.click();
        await page.getByRole("menuitem", { name: /logout|sign out/i }).click();
      }
    }

    // After logout, should be on login page
    await expect(page).toHaveURL(/\/login/, { timeout: 10_000 });
  });
});

test.describe("Authentication guard", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("unauthenticated access to dashboard redirects to login", async ({ page }) => {
    await page.goto(`${BASE_URL}/`);
    // Should redirect to login
    await expect(page).toHaveURL(/\/login/, { timeout: 10_000 });
  });

  test("unauthenticated access to patients redirects to login", async ({ page }) => {
    await page.goto(`${BASE_URL}/patients`);
    await expect(page).toHaveURL(/\/login/, { timeout: 10_000 });
  });
});
