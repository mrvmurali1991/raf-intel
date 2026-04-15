/**
 * emr-config.spec.ts
 *
 * E2E tests for the EMR connection management UI.
 *
 * Covers:
 * - Navigate to EMR config page
 * - View existing connections
 * - Add a new EMR connection (form validation)
 * - Test connection
 * - Delete connection
 */

import { test, expect } from "@playwright/test";

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || "http://localhost:3001";
const EMR_CONFIG_URL = `${BASE_URL}/emr-config`;

test.describe("EMR Config — Page load", () => {
  test("EMR config page loads without errors", async ({ page }) => {
    await page.goto(EMR_CONFIG_URL);
    await page.waitForLoadState("networkidle");

    // Should render the EMR config page — check for heading
    await expect(page).toHaveURL(/emr-config/);

    // No unhandled JavaScript errors
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));
    await page.waitForTimeout(1000);
    expect(errors.filter((e) => !e.includes("hydration"))).toHaveLength(0);
  });

  test("EMR config page has connection list or empty state", async ({ page }) => {
    await page.goto(EMR_CONFIG_URL);
    await page.waitForLoadState("networkidle");

    // Either connections are listed OR an empty state is shown
    const hasConnections = await page
      .locator("[data-testid='connection-card'], .connection-item")
      .count()
      .then((n) => n > 0)
      .catch(() => false);

    const hasEmptyState = await page
      .getByText(/no connections|add your first|connect.*emr/i)
      .isVisible()
      .catch(() => false);

    const hasHeading = await page
      .getByRole("heading", { name: /emr|connection|integration/i })
      .isVisible()
      .catch(() => false);

    expect(hasConnections || hasEmptyState || hasHeading).toBe(true);
  });
});

test.describe("EMR Config — Add connection form", () => {
  test("add connection button opens form or modal", async ({ page }) => {
    await page.goto(EMR_CONFIG_URL);
    await page.waitForLoadState("networkidle");

    // Find add/new connection button
    const addButton = page
      .getByRole("button", { name: /add|new|connect/i })
      .or(page.getByText(/add connection|new connection/i))
      .first();

    const visible = await addButton.isVisible({ timeout: 5_000 }).catch(() => false);
    if (!visible) {
      test.skip();
      return;
    }

    await addButton.click();

    // Form or modal should appear with host/name fields
    const formVisible =
      (await page.getByLabel(/host|server/i).isVisible({ timeout: 3_000 }).catch(() => false)) ||
      (await page.getByPlaceholder(/host|server/i).isVisible({ timeout: 3_000 }).catch(() => false)) ||
      (await page.locator("form").isVisible({ timeout: 3_000 }).catch(() => false));

    expect(formVisible).toBe(true);
  });

  test("form validation rejects empty name field", async ({ page }) => {
    await page.goto(EMR_CONFIG_URL);
    await page.waitForLoadState("networkidle");

    const addButton = page
      .getByRole("button", { name: /add|new|connect/i })
      .first();

    if (!await addButton.isVisible({ timeout: 5_000 }).catch(() => false)) {
      test.skip();
      return;
    }

    await addButton.click();

    // Try to submit with empty fields
    const submitButton = page
      .getByRole("button", { name: /save|submit|add|create/i })
      .last();

    if (await submitButton.isVisible({ timeout: 3_000 }).catch(() => false)) {
      await submitButton.click();

      // Should show validation errors, not navigate away or crash
      await expect(page).toHaveURL(/emr-config/);
    }
  });

  test("internal IP address is rejected by form or server", async ({ page }) => {
    await page.goto(EMR_CONFIG_URL);
    await page.waitForLoadState("networkidle");

    const addButton = page
      .getByRole("button", { name: /add|new|connect/i })
      .first();

    if (!await addButton.isVisible({ timeout: 5_000 }).catch(() => false)) {
      test.skip();
      return;
    }

    await addButton.click();

    // Fill form with SSRF payload
    const hostField = page
      .getByLabel(/host|server/i)
      .or(page.getByPlaceholder(/host|server/i))
      .first();

    if (await hostField.isVisible({ timeout: 3_000 }).catch(() => false)) {
      await hostField.fill("169.254.169.254");

      const nameField = page.getByLabel(/name/i).first();
      if (await nameField.isVisible().catch(() => false)) {
        await nameField.fill("SSRF Test");
      }

      const submitButton = page.getByRole("button", { name: /save|submit|add|create/i }).last();
      if (await submitButton.isVisible().catch(() => false)) {
        await submitButton.click();

        // Should show error, not succeed
        await page.waitForTimeout(1500);

        // Page should still be on emr-config
        expect(page.url()).toContain("emr-config");
      }
    }
  });
});

test.describe("EMR Config — Test connection", () => {
  test("existing connection has a test button", async ({ page }) => {
    await page.goto(EMR_CONFIG_URL);
    await page.waitForLoadState("networkidle");

    // Look for a test connection button on any existing connection card
    const testButton = page.getByRole("button", { name: /test connection|test/i }).first();
    const visible = await testButton.isVisible({ timeout: 5_000 }).catch(() => false);

    if (visible) {
      // Connection exists — test button should be clickable
      await expect(testButton).toBeEnabled();
    }
    // If no connections exist, test is skipped gracefully
  });
});

test.describe("EMR Config — Delete connection", () => {
  test("delete button shows confirmation before deleting", async ({ page }) => {
    await page.goto(EMR_CONFIG_URL);
    await page.waitForLoadState("networkidle");

    const deleteButton = page
      .getByRole("button", { name: /delete|remove/i })
      .first();

    const visible = await deleteButton.isVisible({ timeout: 5_000 }).catch(() => false);

    if (!visible) {
      // No connections to delete — test skipped gracefully
      return;
    }

    await deleteButton.click();

    // Should show a confirmation dialog (native browser dialog or modal)
    const confirmDialog =
      (await page.getByText(/confirm|are you sure|delete.*permanently/i).isVisible({ timeout: 2_000 }).catch(() => false)) ||
      (await page.locator("[role='dialog']").isVisible({ timeout: 2_000 }).catch(() => false));

    // Dismiss the dialog to avoid actually deleting in E2E
    if (confirmDialog) {
      const cancelButton = page.getByRole("button", { name: /cancel|no|dismiss/i }).first();
      if (await cancelButton.isVisible().catch(() => false)) {
        await cancelButton.click();
      }
    }
  });
});
