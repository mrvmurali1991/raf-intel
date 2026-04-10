/**
 * demo-paste.spec.ts
 *
 * E2E tests for the RAF Intelligence Pipeline Demo page.
 *
 * Two suites are covered:
 *   1. Paste Mode  — user pastes a clinical note and runs the pipeline.
 *   2. Patient Mode — user selects a patient and encounter from OpenEMR, then
 *                     runs the pipeline.
 *
 * Login strategy:
 *   The login page shows a "Demo Credentials" list with one row per preset
 *   role (Admin, Clinician, Coder).  Clicking a row auto-fills the email and
 *   password fields.  We then click the "Sign In" submit button.
 *
 * Pipeline completion signal:
 *   The progress label reads "Pipeline Complete" once all 8 steps finish.
 *   We wait up to 120 seconds for this text to appear.
 */

import { test, expect, type Page, type Locator } from "@playwright/test";
import * as path from "path";
import * as fs from "fs";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const BASE_URL = "https://raf.comercioit.com";

/**
 * Complex clinical note used for paste-mode testing.
 * Chosen to produce >= 4 distinct HCC codes and a RAF score > 1.0.
 */
const TEST_CLINICAL_NOTE = `84-year-old male with chronic disease burden.
Past Medical History: Congestive heart failure (systolic), COPD severe, CKD stage 4, Type 2 diabetes with neuropathy, Vascular dementia, Atrial fibrillation.
Physical Exam: BP 148/88, HR 92 irregular, O2 90% on 2L. Bilateral crackles, 2+ edema, oriented x2.
Assessment: I50.22 CHF, J44.1 COPD, E11.22 DM with CKD, N18.4 CKD4, I48.91 AFib, F01.50 Dementia.
Medications: Lisinopril, Metoprolol, Furosemide, Insulin, Warfarin, Sertraline.`;

/** Maximum time (ms) to wait for "Pipeline Complete" text. */
const PIPELINE_TIMEOUT_MS = 120_000;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Ensures the screenshot output directory exists and saves a screenshot with
 * a descriptive name.  Falls back silently if the directory cannot be created.
 */
async function takeScreenshot(page: Page, label: string): Promise<void> {
  const dir = path.join(__dirname, "..", "test-results", "screenshots");
  try {
    fs.mkdirSync(dir, { recursive: true });
  } catch {
    // Directory may already exist — not a failure condition.
  }
  const safeName = label.replace(/[^a-z0-9-_]/gi, "_").toLowerCase();
  const filePath = path.join(dir, `${safeName}-${Date.now()}.png`);
  await page.screenshot({ path: filePath, fullPage: true });
  console.log(`Screenshot saved: ${filePath}`);
}

/**
 * Navigate to /login and authenticate with the Admin preset credentials.
 *
 * The login page renders a "Demo Credentials" panel with three rows — each row
 * is a <button> that, when clicked, auto-fills the email and password inputs.
 * We click the row whose visible text contains "Admin", then submit the form.
 *
 * After successful login the app redirects to "/" (dashboard).
 */
async function loginAsAdmin(page: Page): Promise<void> {
  await page.goto(`${BASE_URL}/login`, { waitUntil: "networkidle" });
  await takeScreenshot(page, "01-login-page-loaded");

  // The demo-credentials list renders one <button> per account.
  // Each button contains the role badge text (Admin / Clinician / Coder).
  // We target the row that contains the "Admin" badge span.
  const adminRow: Locator = page
    .locator("button")
    .filter({ hasText: /Admin/i })
    .first();

  await adminRow.waitFor({ state: "visible", timeout: 10_000 });
  await adminRow.click();
  await takeScreenshot(page, "02-admin-credentials-filled");

  // Verify the email input was populated by the preset button.
  const emailInput = page.locator('input[type="email"]');
  await expect(emailInput).toHaveValue("admin@raf.health", { timeout: 5_000 });

  // Submit the login form.
  const signInButton = page.getByRole("button", { name: /sign in/i });
  await signInButton.click();
  await takeScreenshot(page, "03-sign-in-clicked");

  // Wait for the redirect to the dashboard root.
  await page.waitForURL(`${BASE_URL}/`, { timeout: 30_000 });
  await takeScreenshot(page, "04-dashboard-loaded");
}

/**
 * Wait for the "Pipeline Complete" label to appear in the progress section.
 * The label is rendered as plain text inside a <span> element.
 */
async function waitForPipelineComplete(page: Page): Promise<void> {
  await expect(
    page.getByText("Pipeline Complete", { exact: true })
  ).toBeVisible({ timeout: PIPELINE_TIMEOUT_MS });
}

// ---------------------------------------------------------------------------
// Suite 1: Paste Mode
// ---------------------------------------------------------------------------

test.describe("Pipeline Demo — Paste Mode", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test("should run the full pipeline on a pasted clinical note and return valid results", async ({
    page,
  }) => {
    // -----------------------------------------------------------------------
    // Step 5: Navigate to /demo
    // -----------------------------------------------------------------------
    await page.goto(`${BASE_URL}/demo`, { waitUntil: "networkidle" });
    await takeScreenshot(page, "05-demo-page-loaded");

    // Confirm the page heading is present so we know the route rendered.
    await expect(page.getByText("AI Pipeline", { exact: false })).toBeVisible({
      timeout: 10_000,
    });

    // -----------------------------------------------------------------------
    // Step 6: Click the "Paste Clinical Note" tab
    // -----------------------------------------------------------------------
    // The Tabs component renders <button role="tab"> elements inside a TabsList.
    // The trigger value is "paste" and its visible text is "Paste Clinical Note".
    const pasteTab = page.getByRole("tab", { name: /paste clinical note/i });
    await pasteTab.waitFor({ state: "visible", timeout: 10_000 });
    await pasteTab.click();
    await takeScreenshot(page, "06-paste-tab-selected");

    // The textarea should now be visible.
    const textarea = page.locator("textarea");
    await expect(textarea).toBeVisible({ timeout: 5_000 });

    // -----------------------------------------------------------------------
    // Step 7: Fill the textarea with the test clinical note
    // -----------------------------------------------------------------------
    await textarea.click();
    await textarea.fill(TEST_CLINICAL_NOTE);
    await takeScreenshot(page, "07-clinical-note-filled");

    // Confirm the note was entered correctly (partial match is sufficient).
    await expect(textarea).toContainText("84-year-old male");

    // -----------------------------------------------------------------------
    // Step 8: Click "Run Pipeline"
    // -----------------------------------------------------------------------
    const runButton = page.getByRole("button", { name: /run pipeline/i });
    await expect(runButton).toBeEnabled({ timeout: 5_000 });
    await runButton.click();
    await takeScreenshot(page, "08-run-pipeline-clicked");

    // The button label changes to "Pipeline Running..." while in progress.
    await expect(
      page.getByRole("button", { name: /pipeline running/i })
    ).toBeVisible({ timeout: 10_000 });
    await takeScreenshot(page, "09-pipeline-running");

    // -----------------------------------------------------------------------
    // Step 9: Wait for "Pipeline Complete"
    // -----------------------------------------------------------------------
    await waitForPipelineComplete(page);
    await takeScreenshot(page, "10-pipeline-complete");

    // -----------------------------------------------------------------------
    // Step 10: Verify at least 4 HCC codes are displayed
    // -----------------------------------------------------------------------
    // HCC codes appear as <span> badges with text matching /HCC\d+/.
    // They are rendered in the Step 6 (RAF Calculation) breakdown table and
    // in the Step 7 (Gap Analysis) section.
    // We collect all unique HCC badge texts visible on the page.
    const hccBadges = page.locator("text=/^HCC\\d+$/");
    const hccCount = await hccBadges.count();
    console.log(`HCC codes found on page: ${hccCount}`);

    // Also check via the RAF breakdown table rows which each carry an HCC badge.
    // If the exact badge selector does not match, fall back to a broader check.
    if (hccCount < 4) {
      // Broader search: any element whose text content starts with "HCC" followed
      // by digits, including elements with surrounding whitespace.
      const allHccElements = await page
        .locator("*")
        .filter({ hasText: /\bHCC\d+\b/ })
        .all();
      console.log(
        `Broader HCC element count (may include duplicates): ${allHccElements.length}`
      );
    }

    expect(hccCount, "Expected at least 4 HCC codes in the results").toBeGreaterThanOrEqual(4);
    await takeScreenshot(page, "11-hcc-codes-verified");

    // -----------------------------------------------------------------------
    // Step 11: Verify RAF score > 1.0 is displayed
    // -----------------------------------------------------------------------
    // The RAF score is shown as a large number inside the Step 6 card.
    // The exact text is formatted to 3 decimal places (e.g. "2.456").
    // We look for the "Total RAF Score" label then get the adjacent number.
    const rafSection = page.locator("text=Total RAF Score").locator("..");
    await expect(rafSection).toBeVisible({ timeout: 5_000 });

    // Extract the numeric value rendered near the label.
    // The score element is a large <div> sibling with class containing font-black.
    const rafScoreElement = page
      .locator("div")
      .filter({ hasText: /^\d+\.\d{3}$/ })
      .first();

    await rafScoreElement.waitFor({ state: "visible", timeout: 10_000 });
    const rafText = (await rafScoreElement.textContent()) ?? "0";
    const rafScore = parseFloat(rafText.trim());

    console.log(`RAF score displayed: ${rafScore}`);
    expect(rafScore, `RAF score "${rafScore}" should be greater than 1.0`).toBeGreaterThan(1.0);
    await takeScreenshot(page, "12-raf-score-verified");
  });
});

// ---------------------------------------------------------------------------
// Suite 2: Patient (OpenEMR) Mode
// ---------------------------------------------------------------------------

test.describe("Pipeline Demo — Patient (OpenEMR) Mode", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test("should run the full pipeline on the first patient with clinical notes and return results", async ({
    page,
  }) => {
    // -----------------------------------------------------------------------
    // Step 1: Navigate to /demo
    // -----------------------------------------------------------------------
    await page.goto(`${BASE_URL}/demo`, { waitUntil: "networkidle" });
    await takeScreenshot(page, "p-01-demo-page-loaded");

    // -----------------------------------------------------------------------
    // Step 2: Click "Select from OpenEMR" tab
    // -----------------------------------------------------------------------
    const openEMRTab = page.getByRole("tab", { name: /select from openemr/i });
    await openEMRTab.waitFor({ state: "visible", timeout: 10_000 });
    await openEMRTab.click();
    await takeScreenshot(page, "p-02-openemr-tab-selected");

    // -----------------------------------------------------------------------
    // Step 3: Select the first patient from the dropdown
    // -----------------------------------------------------------------------
    // The patient <select> has a default empty option "Select patient...".
    // Patients are loaded asynchronously; wait for at least one real option.
    const patientSelect = page.locator("select").first();
    await expect(patientSelect).toBeVisible({ timeout: 10_000 });

    // Wait until the dropdown has more than just the placeholder option.
    await expect(async () => {
      const options = await patientSelect.locator("option").all();
      expect(options.length).toBeGreaterThan(1);
    }).toPass({ timeout: 20_000, intervals: [1_000] });

    await takeScreenshot(page, "p-03-patient-list-loaded");

    // Select the first real patient option (index 1 — index 0 is the placeholder).
    await patientSelect.selectOption({ index: 1 });
    await takeScreenshot(page, "p-04-patient-selected");

    // -----------------------------------------------------------------------
    // Step 4: Select the first encounter that has clinical notes
    // -----------------------------------------------------------------------
    // Encounters are fetched after the patient selection.
    const encounterSelect = page.locator("select").nth(1);
    await expect(encounterSelect).toBeVisible({ timeout: 10_000 });

    // Wait for the encounter list to populate.
    await expect(async () => {
      const options = await encounterSelect.locator("option").all();
      // Need at least 2 options (placeholder + one encounter).
      expect(options.length).toBeGreaterThan(1);
    }).toPass({ timeout: 20_000, intervals: [1_000] });

    await takeScreenshot(page, "p-05-encounter-list-loaded");

    // Find the first encounter option that contains "Has Notes" marker.
    // The option text format is: "#<id> — <date> - <reason> ✓ Has Notes"
    // Options without notes are rendered with "— No Notes" and disabled.
    const allEncounterOptions = await encounterSelect.locator("option").all();
    let selectedEncounter = false;

    for (const option of allEncounterOptions) {
      const optionText = await option.textContent();
      const isDisabled = await option.getAttribute("disabled");

      if (optionText && optionText.includes("Has Notes") && isDisabled === null) {
        const optionValue = await option.getAttribute("value");
        if (optionValue) {
          await encounterSelect.selectOption({ value: optionValue });
          selectedEncounter = true;
          console.log(`Selected encounter: ${optionText.trim()}`);
          break;
        }
      }
    }

    if (!selectedEncounter) {
      // If no encounter with "Has Notes" label was found, select index 1 and
      // proceed — the test will surface whether the pipeline handles this.
      await encounterSelect.selectOption({ index: 1 });
      console.warn("No encounter with clinical notes found; selected first available encounter.");
    }

    await takeScreenshot(page, "p-06-encounter-selected");

    // -----------------------------------------------------------------------
    // Step 5: Verify the Clinical Notes section appears in the preview
    // -----------------------------------------------------------------------
    // After selecting an encounter with notes the preview section renders:
    //   - Patient Information card
    //   - Data stats grid
    //   - "Clinical Notes" heading inside the Encounter Details card
    //
    // We give a generous timeout because the preview requires several API calls.
    const clinicalNotesHeading = page.getByText(/clinical notes/i).first();
    await clinicalNotesHeading.waitFor({ state: "visible", timeout: 30_000 });
    await takeScreenshot(page, "p-07-clinical-notes-visible");

    // -----------------------------------------------------------------------
    // Step 6: Click "Run Pipeline"
    // -----------------------------------------------------------------------
    const runButton = page.getByRole("button", { name: /run pipeline/i });
    await expect(runButton).toBeEnabled({ timeout: 10_000 });
    await runButton.click();
    await takeScreenshot(page, "p-08-run-pipeline-clicked");

    // The button transitions to "Pipeline Running..." while the API processes.
    await expect(
      page.getByRole("button", { name: /pipeline running/i })
    ).toBeVisible({ timeout: 15_000 });
    await takeScreenshot(page, "p-09-pipeline-running");

    // -----------------------------------------------------------------------
    // Step 7: Wait for pipeline completion (up to 120 s)
    // -----------------------------------------------------------------------
    await waitForPipelineComplete(page);
    await takeScreenshot(page, "p-10-pipeline-complete");

    // -----------------------------------------------------------------------
    // Step 8: Verify results are present
    // -----------------------------------------------------------------------

    // 8a. The 8-step progress indicator should show all steps as done.
    //     Each completed step renders a CheckCircle2 icon inside a button.
    //     The progress label already confirmed completion; also verify the
    //     step count badge "8/8 steps".
    const stepCounter = page.getByText("8/8 steps");
    await expect(stepCounter).toBeVisible({ timeout: 5_000 });
    await takeScreenshot(page, "p-11-steps-8-of-8");

    // 8b. RAF score section should be visible (Step 6 — RAF Calculation).
    //     The "Total RAF Score" label is rendered inside Step 6 content
    //     when that step's accordion panel is expanded.
    //     If not already expanded, click the Step 6 (RAF) step indicator button.
    const rafStepButton = page
      .locator("button")
      .filter({ hasText: /RAF/i })
      .filter({ has: page.locator("svg") }) // The step indicator contains an icon
      .first();

    // If the RAF step button is present and the score section is not yet visible,
    // click the button to expand the step's detail panel.
    const totalRafLabel = page.getByText("Total RAF Score");
    const isRafVisible = await totalRafLabel.isVisible().catch(() => false);

    if (!isRafVisible) {
      // Try clicking the RAF step indicator to expand its panel.
      await rafStepButton.click().catch(() => {
        // The step indicator may not be clickable if already expanded.
      });
    }

    // 8c. Verify at least one HCC badge is present in the results.
    const hccBadges = page.locator("text=/^HCC\\d+$/");
    const hccCount = await hccBadges.count();
    console.log(`Patient mode — HCC codes found: ${hccCount}`);

    // Patient mode may yield fewer HCC codes depending on the encounter selected,
    // so we assert at least 1 HCC code is found rather than requiring 4.
    expect(
      hccCount,
      "Expected at least 1 HCC code in patient mode results"
    ).toBeGreaterThanOrEqual(1);

    await takeScreenshot(page, "p-12-results-verified");

    // 8d. The gap analysis section (Step 7) title should be visible.
    await expect(
      page.getByText(/gap analysis/i).first()
    ).toBeVisible({ timeout: 10_000 });

    await takeScreenshot(page, "p-13-gap-analysis-visible");
  });
});
