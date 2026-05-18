/**
 * patient-page-cohesion.spec.ts
 *
 * E2E assertions for the coder-first IA refactor of /patients/[pid].
 *
 * Tests:
 *   1. Hero strip renders patient name + insurance badge
 *   2. Risk summary card renders numeric RAF value
 *   3. HCC suspect card expands on click → MEAT evidence visible
 *   4. axe-core: 0 critical/serious violations
 *
 * Strategy:
 *   - Route-mock all backend calls so the suite runs without a live API.
 *   - Seed an auth cookie + mock /api/auth/me so AuthProvider boots.
 *   - Mock patient / suspects / hedis / raf-breakdown endpoints.
 *   - Skip the whole suite if the front-end dev server is unreachable
 *     (CI=true guard still respected; AXE_BASE_URL defaults to :3444).
 *
 * Run:
 *   npx playwright test tests/e2e/patient-page-cohesion.spec.ts
 */

import { test, expect, type BrowserContext } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL ?? process.env.AXE_BASE_URL ?? "http://localhost:3444";
const PATIENT_ID = 3;

// ---------------------------------------------------------------------------
// Auth + stub helpers
// ---------------------------------------------------------------------------

async function seedAuthAndMocks(context: BrowserContext): Promise<void> {
  const url = new URL(BASE_URL);

  // Auth cookie
  await context.addCookies([
    {
      name: "raf_authenticated",
      value: "true",
      domain: url.hostname,
      path: "/",
      httpOnly: false,
      secure: url.protocol === "https:",
      sameSite: "Lax",
    },
  ]);

  // Auth me
  await context.route("**/api/auth/me", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: 1,
        email: "coder@test.health",
        role: "admin",
        first_name: "Test",
        last_name: "Coder",
      }),
    })
  );

  await context.route("**/api/auth/refresh", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ access_token: "e2e-test-token" }),
    })
  );

  // Patient core
  await context.route(/\/api\/patients\/3$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: 3,
        pid: 3,
        fname: "Alexandra",
        lname: "Rivera",
        DOB: "1955-03-14",
        sex: "Female",
        mrn: "MRN-00003",
      }),
    })
  );

  // Patient profile (provides insurance plan + enrollment info)
  await context.route(/\/api\/patients\/3\/profile/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        enrollment: {
          plan_name: "BlueCross Medicare Adv",
          mbi: "1EG4-TE5-MK72",
          payer: "BlueCross",
          source: "eligibility",
        },
        primary_provider: "Dr. Kim",
        vitals: { latest: null },
        labs: { results: [] },
        billing: { icd10_codes: ["E11.9", "I10"] },
        demographics: { race: "Hispanic", language: "en" },
        immunizations: [],
      }),
    })
  );

  // RAF breakdown
  await context.route(/\/api\/raf\/breakdown\/3/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        final_raf: 1.847,
        total_raf: 1.847,
        hcc_details: [
          {
            hcc_code: "HCC19",
            hcc_label: "Diabetes without complications",
            coefficient: 0.105,
            meat_evidence: { monitor: true, evaluate: false, assess: true, treat: true },
          },
          {
            hcc_code: "HCC85",
            hcc_label: "Congestive Heart Failure",
            coefficient: 0.323,
            meat_evidence: { monitor: true, evaluate: true, assess: true, treat: true },
          },
        ],
        model_segment: "CNA",
        demographic_base: 0.362,
        measurement_year: 2026,
      }),
    })
  );

  // RAF history (for prior-year RAF)
  await context.route(/\/api\/raf\/history\/3/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        scores: [
          { year: 2025, raf_score: 1.712 },
          { year: 2024, raf_score: 1.540 },
        ],
      }),
    })
  );

  // HCC Suspects — provide one suspect with MEAT evidence
  await context.route(/\/api\/patients\/3\/suspects/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        suspects: [
          {
            id: 101,
            suspected_condition: "Chronic Kidney Disease, Stage 3",
            suspect_icd10: "N18.3",
            suspect_hcc: 137,
            confidence_score: 0.82,
            hcc_coefficient: 0.289,
            rationale: "eGFR 42 mL/min on 2026-02-10 lab. CKD stage 3 criteria met.",
            evidence: "Lab: eGFR 42 mL/min (2026-02-10). Creatinine 1.8 mg/dL.",
            meat_evidence: {
              monitor: "eGFR monitored every 6 months",
              evaluate: false,
              assess: "Nephrology referral ordered",
              treat: "ACE inhibitor prescribed",
            },
            source: "Lab evidence",
            source_document_name: "nephrology_consult_2026-02-10.pdf",
            source_document_page: 3,
          },
        ],
        total: 1,
      }),
    })
  );

  // HEDIS gaps
  await context.route(/\/api\/hedis\/patient\/3\/gaps/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        open_gaps: [
          { measure_id: "HBD", status: "open", last_value: "A1c 8.4%" },
        ],
        all_gaps: [
          { measure_id: "HBD", status: "open", last_value: "A1c 8.4%" },
          { measure_id: "CBP", status: "met", last_value: "128/78" },
        ],
      }),
    })
  );

  // Encounters
  await context.route(/\/api\/patients\/3\/encounters/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        encounters: [
          {
            encounter_id: 500,
            date: "2025-11-20",
            encounter_date: "2025-11-20",
            reason: "Annual wellness visit",
          },
        ],
      }),
    })
  );

  // V28 impact
  await context.route(/\/api\/v28-impact\/patient\/3/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        patient_id: 3,
        v24_raf: 2.01,
        v28_raf: 1.847,
        raf_delta: -0.163,
        raf_delta_pct: -8.1,
        revenue_delta_annual: -1630,
        dropped_hccs: ["HCC100"],
        gained_hccs: [],
        common_hccs: ["HCC19", "HCC85"],
        icd_count: 5,
        model_segment: "CNA",
      }),
    })
  );

  // Catch-all for remaining patient sub-endpoints
  await context.route(/\/api\/patients\/3\/.*/, (route) => {
    if (!route.request().url().includes("suspects") &&
        !route.request().url().includes("profile") &&
        !route.request().url().includes("encounters")) {
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items: [], results: [], suspects: [], medications: [], problems: [] }),
      });
    } else {
      route.fallback();
    }
  });

  // Catch-all for raf sub-endpoints not already matched
  await context.route(/\/api\/raf\/.*/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({}),
    })
  );

  // Suppress onboarding
  await context.addInitScript(() => {
    try {
      window.localStorage.setItem("raf_onboarding_complete", "true");
    } catch { /* sandboxed */ }
  });
}

// ---------------------------------------------------------------------------
// Reachability check
// ---------------------------------------------------------------------------

async function frontendReachable(): Promise<boolean> {
  try {
    const { request: pwRequest } = await import("@playwright/test");
    const ctx = await pwRequest.newContext({ ignoreHTTPSErrors: true });
    const res = await ctx.get(`${BASE_URL}/login`, { timeout: 5000 });
    await ctx.dispose();
    return res.status() < 500;
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe("Patient page cohesion — coder-first IA", () => {
  test.beforeAll(async () => {
    if (!await frontendReachable()) {
      test.skip();
    }
  });

  test("hero strip shows patient name + insurance badge", async ({ page, context }) => {
    await seedAuthAndMocks(context);
    await page.goto(`${BASE_URL}/patients/${PATIENT_ID}`, { waitUntil: "domcontentloaded" });

    // Wait for the name to appear in h1
    const nameHeading = page.locator("h1.patient-name-h1, h1[class*='patient-name']").first();
    await expect(nameHeading).toBeVisible({ timeout: 10_000 });
    await expect(nameHeading).toContainText("Rivera");

    // Insurance badge from profile enrollment
    await expect(page.getByText("BlueCross Medicare Adv")).toBeVisible({ timeout: 8_000 });
  });

  test("risk summary card shows numeric RAF value", async ({ page, context }) => {
    await seedAuthAndMocks(context);
    await page.goto(`${BASE_URL}/patients/${PATIENT_ID}`, { waitUntil: "domcontentloaded" });

    // The RAF score (1.847) should appear in the risk summary card
    // Allow some leeway for the count-up animation to settle
    await expect(page.getByText(/1\.8\d\d/).first()).toBeVisible({ timeout: 12_000 });
  });

  test("HCC card click expands with MEAT evidence", async ({ page, context }) => {
    await seedAuthAndMocks(context);
    await page.goto(`${BASE_URL}/patients/${PATIENT_ID}`, { waitUntil: "domcontentloaded" });

    // Wait for the action items panel to render the suspect card
    const suspectCard = page.getByText("Chronic Kidney Disease, Stage 3").first();
    await expect(suspectCard).toBeVisible({ timeout: 10_000 });

    // Click to expand — the card div is the clickable ancestor
    await suspectCard.click();

    // After expansion, MEAT evidence section should be visible
    await expect(
      page.getByText(/MEAT Documentation/i).first()
    ).toBeVisible({ timeout: 5_000 });

    // Source doc chip should also be visible
    await expect(
      page.getByText(/nephrology_consult_2026-02-10\.pdf/i).first()
    ).toBeVisible({ timeout: 5_000 });
  });

  test("axe-core returns 0 critical/serious violations", async ({ page, context }) => {
    await seedAuthAndMocks(context);
    await page.goto(`${BASE_URL}/patients/${PATIENT_ID}`, { waitUntil: "domcontentloaded" });

    // Let the page settle (count-up animation, lazy queries)
    await page.waitForTimeout(1_500);

    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa"])
      // Exclude third-party embedded iframes if any
      .exclude("iframe")
      .analyze();

    const criticalOrSerious = results.violations.filter(
      (v) => v.impact === "critical" || v.impact === "serious"
    );

    if (criticalOrSerious.length > 0) {
      const summary = criticalOrSerious
        .map((v) => `[${v.impact}] ${v.id}: ${v.description} (${v.nodes.length} nodes)`)
        .join("\n");
      throw new Error(
        `axe-core found ${criticalOrSerious.length} critical/serious violations:\n${summary}`
      );
    }

    expect(criticalOrSerious).toHaveLength(0);
  });
});
