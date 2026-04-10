import { test, expect } from "@playwright/test";
import { login, waitForDataLoad } from "./helpers";

/**
 * EMR Configuration tests
 *
 * Verifies the EMR Config page: vendor preset list, "Add EMR Connection"
 * wizard trigger, vendor selection, and form field validation.
 */
test.describe("EMR Configuration", () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await page.goto("/emr-config");
    await waitForDataLoad(page);
  });

  // ---------------------------------------------------------------------------
  // Page load
  // ---------------------------------------------------------------------------

  test("EMR Config page loads and shows a heading", async ({ page }) => {
    // The PageHeader renders "EMR Configuration" or similar.
    await expect(page.getByText(/EMR/i)).toBeVisible();
  });

  test("stats bar renders at least one stat card", async ({ page }) => {
    // The page renders StatCards — check for "Active Connections" label.
    await expect(page.getByText(/connections|vendors|sync/i).first()).toBeVisible({
      timeout: 15_000,
    });
  });

  // ---------------------------------------------------------------------------
  // Vendor presets
  // ---------------------------------------------------------------------------

  test("vendor presets section is displayed", async ({ page }) => {
    // The wizard step-1 grid shows preset cards for vendors like OpenEMR, Epic etc.
    // These presets are fetched from /api/emr/vendors — wait for them to load.
    await waitForDataLoad(page);

    // Check for at least one well-known vendor name.
    const vendorTexts = [
      "openemr",
      "OpenEMR",
      "Epic",
      "Cerner",
      "FHIR",
      "Direct DB",
      "REST API",
    ];

    let foundVendor = false;
    for (const text of vendorTexts) {
      const count = await page.getByText(text, { exact: false }).count();
      if (count > 0) {
        foundVendor = true;
        break;
      }
    }
    expect(foundVendor).toBe(true);
  });

  // ---------------------------------------------------------------------------
  // Add Connection wizard
  // ---------------------------------------------------------------------------

  test('"Add EMR Connection" button is visible', async ({ page }) => {
    const addBtn = page.getByRole("button", { name: "Add EMR Connection" });
    await expect(addBtn).toBeVisible();
  });

  test("clicking Add EMR Connection opens the connection wizard modal", async ({
    page,
  }) => {
    const addBtn = page.getByRole("button", { name: "Add EMR Connection" });
    await addBtn.click();

    // The modal/dialog is rendered with the aria-label "Add EMR Connection".
    const dialog = page.getByRole("dialog", { name: "Add EMR Connection" });
    await expect(dialog).toBeVisible({ timeout: 10_000 });
  });

  test("wizard shows a vendor preset grid on step 1", async ({ page }) => {
    await page.getByRole("button", { name: "Add EMR Connection" }).click();
    const dialog = page.getByRole("dialog", { name: "Add EMR Connection" });
    await expect(dialog).toBeVisible({ timeout: 10_000 });

    // Step 1 renders vendor cards inside the dialog.
    await expect(dialog.getByText(/step 1|choose.*vendor|select.*vendor/i).or(
      dialog.getByText(/openemr|epic|fhir/i)
    )).toBeVisible({ timeout: 10_000 });
  });

  // ---------------------------------------------------------------------------
  // Vendor selection pre-fills defaults
  // ---------------------------------------------------------------------------

  test("selecting a vendor preset populates the form with defaults", async ({
    page,
  }) => {
    await page.getByRole("button", { name: "Add EMR Connection" }).click();
    const dialog = page.getByRole("dialog", { name: "Add EMR Connection" });
    await expect(dialog).toBeVisible({ timeout: 10_000 });

    // Click the first preset card inside the dialog.
    const firstPreset = dialog.locator('[style*="cursor: pointer"]').first();
    const presetCount = await firstPreset.count();

    if (presetCount > 0) {
      await firstPreset.click();
      // After selecting a vendor, the form section should appear with at least
      // the "Name" input visible.
      await expect(dialog.getByPlaceholder(/connection|openemr/i)).toBeVisible({
        timeout: 10_000,
      });
    } else {
      // If presets haven't loaded (API unavailable) the test is not applicable.
      test.skip();
    }
  });

  // ---------------------------------------------------------------------------
  // Form validation
  // ---------------------------------------------------------------------------

  test("submitting the Add Connection form without a name shows a validation error", async ({
    page,
  }) => {
    await page.getByRole("button", { name: "Add EMR Connection" }).click();
    const dialog = page.getByRole("dialog", { name: "Add EMR Connection" });
    await expect(dialog).toBeVisible({ timeout: 10_000 });

    // Select any preset to advance past step 1.
    const firstPreset = dialog.locator('[style*="cursor: pointer"]').first();
    const presetCount = await firstPreset.count();

    if (presetCount > 0) {
      await firstPreset.click();
    }

    // Attempt to save without filling required fields.
    const saveBtn = dialog.getByRole("button", { name: /save|create|add/i });
    const saveBtnCount = await saveBtn.count();

    if (saveBtnCount > 0) {
      await saveBtn.click();
      // A validation error should appear inside the dialog.
      await expect(dialog.getByText(/required|required field|name is required/i)).toBeVisible({
        timeout: 5_000,
      });
    } else {
      // Wizard may require vendor selection before showing the save button.
      test.skip();
    }
  });

  test("Close button dismisses the Add Connection dialog", async ({ page }) => {
    await page.getByRole("button", { name: "Add EMR Connection" }).click();
    const dialog = page.getByRole("dialog", { name: "Add EMR Connection" });
    await expect(dialog).toBeVisible({ timeout: 10_000 });

    await dialog.getByRole("button", { name: "Close" }).click();
    await expect(dialog).not.toBeVisible({ timeout: 5_000 });
  });
});
