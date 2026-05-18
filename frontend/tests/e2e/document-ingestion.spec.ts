/**
 * document-ingestion.spec.ts
 *
 * E2E tests for the /admin/document-ingestion dashboard.
 *
 * Test coverage:
 *   1. Admin loads page → 8 (or 9 with OpenEMR) source cards are visible.
 *   2. KPI tiles render with zero / dash values when backend returns empty data.
 *   3. Clicking a source card appends ?source=<id> to the URL and filters the table.
 *   4. Clicking a table row opens the drawer with document details.
 *   5. axe-core: zero WCAG 2.2 AA contrast violations on the page.
 *
 * Prerequisites:
 *   - NEXT_PUBLIC_API_URL must point to a running backend (or be intercepted by MSW).
 *   - Admin credentials: admin@raf.health / Admin@123
 *
 * Run with:
 *   npx playwright test tests/e2e/document-ingestion.spec.ts
 */

import { test, expect, type Page } from "@playwright/test";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3500";
const ADMIN_EMAIL = "admin@raf.health";
const ADMIN_PASSWORD = "Admin@123";

/** Canonical source IDs expected on the dashboard */
const EXPECTED_SOURCE_IDS = [
  "fhir-bulk",
  "fhir-docref",
  "hl7v2-mdm",
  "direct-ccda",
  "hie",
  "datavant",
  "inovalon",
  "reveleer",
  "openemr",
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function loginAsAdmin(page: Page) {
  await page.goto(`${BASE_URL}/login`);

  // Prefer demo-credential shortcut if available
  const adminRow = page.locator('[data-testid="demo-credential-admin"]');
  if (await adminRow.isVisible({ timeout: 2000 }).catch(() => false)) {
    await adminRow.click();
  } else {
    await page.fill('input[type="email"], input[name="email"]', ADMIN_EMAIL);
    await page.fill('input[type="password"], input[name="password"]', ADMIN_PASSWORD);
  }

  await page.click('button[type="submit"]');
  await page.waitForURL(`${BASE_URL}/`, { timeout: 15_000 });
}

async function goToDashboard(page: Page) {
  await page.goto(`${BASE_URL}/admin/document-ingestion`);
  // Wait for KPI strip to be rendered (at least one KPI card)
  await page.waitForSelector('[role="region"][aria-label="Ingestion KPIs"]', {
    timeout: 20_000,
  });
}

// ---------------------------------------------------------------------------
// Suite
// ---------------------------------------------------------------------------

test.describe("Document Ingestion Dashboard", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  // ── Test 1: Source cards ────────────────────────────────────────────────

  test("renders all 9 source cards after admin login", async ({ page }) => {
    await goToDashboard(page);

    // Cards are role="button" elements with aria-label containing the source name
    const cards = page.locator('[role="button"][aria-pressed]');
    await expect(cards).toHaveCount(EXPECTED_SOURCE_IDS.length, {
      timeout: 15_000,
    });

    // Verify each source card is accessible by aria-label substring
    for (const id of EXPECTED_SOURCE_IDS) {
      const card = page.locator(`[role="button"][aria-label*="${id}"], [role="button"][aria-label*="${id.replace(/-/g, " ")}"]`).first();
      await expect(card).toBeVisible({ timeout: 10_000 });
    }
  });

  // ── Test 2: KPI tiles with no data ──────────────────────────────────────

  test("KPI tiles render with 0 or dash when backend has no data", async ({
    page,
  }) => {
    // Intercept the dashboard API call and return empty data
    await page.route("**/api/admin/document-ingestion/dashboard**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          sources: EXPECTED_SOURCE_IDS.map((id) => ({
            id,
            name: id,
            status: "not_configured",
            docs_24h: 0,
            suspects_24h: 0,
            last_activity: null,
            config_path: `/admin/${id}`,
          })),
          recent_documents: [],
          kpis: {
            total_docs_24h: 0,
            total_suspects_24h: 0,
            success_rate_pct: null,
            active_sources: 0,
            window_hours: 24,
          },
          generated_at: new Date().toISOString(),
        }),
      })
    );

    await goToDashboard(page);

    const kpiRegion = page.locator('[role="region"][aria-label="Ingestion KPIs"]');
    await expect(kpiRegion).toBeVisible();

    // Verify zero values appear — at least two KPI cards show "0"
    const zeroValues = kpiRegion.locator("text=0");
    await expect(zeroValues.first()).toBeVisible();

    // Success rate shows "—" when null
    await expect(kpiRegion.locator("text=—")).toBeVisible();
  });

  // ── Test 3: Source card filter ───────────────────────────────────────────

  test("clicking a source card appends ?source= to URL and filters the table", async ({
    page,
  }) => {
    // Seed some rows for fhir-bulk so the table has content
    await page.route("**/api/admin/document-ingestion/dashboard**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          sources: EXPECTED_SOURCE_IDS.map((id) => ({
            id,
            name: id,
            status: id === "fhir-bulk" ? "active" : "not_configured",
            docs_24h: id === "fhir-bulk" ? 5 : 0,
            suspects_24h: 0,
            last_activity: id === "fhir-bulk" ? new Date().toISOString() : null,
            config_path: `/admin/${id}`,
          })),
          recent_documents: [
            {
              source: "fhir-bulk",
              timestamp: new Date().toISOString(),
              document_id: "doc-001",
              patient_id: "pat-999",
              filename: "patient_export.json",
              mimetype: "application/json",
              suspects: 2,
              status: "success",
            },
            {
              source: "reveleer",
              timestamp: new Date().toISOString(),
              document_id: "doc-002",
              patient_id: "pat-888",
              filename: "chart_pull.pdf",
              mimetype: "application/pdf",
              suspects: 1,
              status: "success",
            },
          ],
          kpis: {
            total_docs_24h: 2,
            total_suspects_24h: 3,
            success_rate_pct: 100,
            active_sources: 1,
            window_hours: 24,
          },
          generated_at: new Date().toISOString(),
        }),
      })
    );

    await goToDashboard(page);

    // Click the fhir-bulk card
    const fhirCard = page
      .locator('[role="button"]')
      .filter({ hasText: /fhir.bulk/i })
      .first();
    await fhirCard.click();

    // URL should now have ?source=fhir-bulk
    await expect(page).toHaveURL(/[?&]source=fhir-bulk/, { timeout: 5_000 });

    // Table should only show the fhir-bulk row
    const tableRows = page.locator('table[aria-label="Recent document activity"] tbody tr');
    await expect(tableRows).toHaveCount(1, { timeout: 5_000 });
    await expect(tableRows.first()).toContainText("fhir-bulk");

    // Clicking same card again should clear the filter
    await fhirCard.click();
    await expect(page).not.toHaveURL(/source=fhir-bulk/);
  });

  // ── Test 4: Row click opens drawer ──────────────────────────────────────

  test("clicking a table row opens the document detail drawer", async ({
    page,
  }) => {
    await page.route("**/api/admin/document-ingestion/dashboard**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          sources: EXPECTED_SOURCE_IDS.map((id) => ({
            id,
            name: id,
            status: "not_configured",
            docs_24h: 0,
            suspects_24h: 0,
            last_activity: null,
            config_path: `/admin/${id}`,
          })),
          recent_documents: [
            {
              source: "openemr",
              timestamp: new Date().toISOString(),
              document_id: "doc-openemr-1",
              patient_id: "pat-123",
              filename: "progress_note.pdf",
              mimetype: "application/pdf",
              suspects: 3,
              status: "success",
            },
          ],
          kpis: {
            total_docs_24h: 1,
            total_suspects_24h: 3,
            success_rate_pct: 100,
            active_sources: 0,
            window_hours: 24,
          },
          generated_at: new Date().toISOString(),
        }),
      })
    );

    // Mock document detail endpoint
    await page.route(
      "**/api/admin/document-ingestion/document/openemr/doc-openemr-1",
      (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            source: "openemr",
            document_id: "doc-openemr-1",
            record: {
              log_id: "doc-openemr-1",
              filename: "progress_note.pdf",
              mimetype: "application/pdf",
              file_size_bytes: 54321,
              processing_engine: "gemini_vision",
              status: "success",
              patient_id: "pat-123",
              ingested_at: new Date().toISOString(),
            },
            suspects: [
              {
                hcc_code: "HCC85",
                icd10_code: "I50.22",
                confidence_score: 0.91,
                evidence_sentence: "Patient has systolic heart failure documented.",
              },
            ],
          }),
        })
    );

    await goToDashboard(page);

    // Click the table row
    const row = page
      .locator('table[aria-label="Recent document activity"] tbody tr')
      .first();
    await expect(row).toBeVisible({ timeout: 10_000 });
    await row.click();

    // Drawer should appear
    const drawer = page.locator('[role="dialog"][aria-label="Document detail"]');
    await expect(drawer).toBeVisible({ timeout: 8_000 });

    // Drawer should show the processing engine
    await expect(drawer).toContainText("gemini_vision");

    // Drawer should show the suspect
    await expect(drawer).toContainText("HCC85");
    await expect(drawer).toContainText("I50.22");

    // Close drawer with ESC
    await page.keyboard.press("Escape");
    await expect(drawer).not.toBeVisible({ timeout: 3_000 });
  });

  // ── Test 5: Accessibility (axe-core) ────────────────────────────────────

  test("zero WCAG 2.2 AA contrast violations on the dashboard", async ({
    page,
  }) => {
    // Stub out API to avoid network dependency in CI
    await page.route("**/api/admin/document-ingestion/dashboard**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          sources: EXPECTED_SOURCE_IDS.map((id) => ({
            id,
            name: id,
            status: "not_configured",
            docs_24h: 0,
            suspects_24h: 0,
            last_activity: null,
            config_path: `/admin/${id}`,
          })),
          recent_documents: [],
          kpis: {
            total_docs_24h: 0,
            total_suspects_24h: 0,
            success_rate_pct: null,
            active_sources: 0,
            window_hours: 24,
          },
          generated_at: new Date().toISOString(),
        }),
      })
    );

    await goToDashboard(page);

    // Inject axe-core from CDN
    await page.addScriptTag({
      url: "https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.9.1/axe.min.js",
    });

    const violations = await page.evaluate(async () => {
      // @ts-ignore — axe is injected at runtime
      const results = await window.axe.run(document, {
        runOnly: {
          type: "tag",
          values: ["wcag2a", "wcag2aa", "wcag22aa"],
        },
        rules: {
          // Only check color-contrast violations
          "color-contrast": { enabled: true },
        },
      });
      return results.violations.filter(
        (v: { id: string }) => v.id === "color-contrast"
      );
    });

    expect(
      violations,
      `Found ${violations.length} color-contrast violations: ${JSON.stringify(violations, null, 2)}`
    ).toHaveLength(0);
  });
});
