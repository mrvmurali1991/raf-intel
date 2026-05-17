import { test, expect, type BrowserContext } from "@playwright/test";

/**
 * Patient-detail point-of-care responsive sanity check.
 *
 * Renders /patients/3 at iPhone-class (414×896) and iPad-portrait
 * (768×1024) viewports, captures full-page screenshots to /tmp, and
 * asserts no horizontal overflow / layout break.
 *
 * Auth strategy: the test only cares about layout, not data. We bypass
 * the Next.js middleware (which only checks the `raf_authenticated`
 * cookie) and seed a synthetic auth token in localStorage so the page
 * tree mounts. Patient data queries may render empty/error states; the
 * sticky header, metric strip, tab list, and demographics row still
 * exercise the responsive CSS, which is what we're screenshotting.
 */

const PATIENT_ID = 3;

// Allow PLAYWRIGHT_BASE_URL override so this spec can run against a local
// dev server (with our CSS edits) while the rest of the suite stays on
// staging. Default falls back to the config's baseURL.
test.use({ baseURL: process.env.PLAYWRIGHT_BASE_URL || undefined });

async function seedAuth(context: BrowserContext, baseURL: string): Promise<void> {
  // Cookie the proxy middleware checks before letting protected pages
  // through. Value doesn't matter — just non-empty and not "false".
  const url = new URL(baseURL);
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

  // Stub the backend so the AuthProvider boot completes as "logged in"
  // and the patient detail page can mount its component tree. Patient
  // tabs render empty/loading states — irrelevant for layout screenshots.
  await context.route("**/api/auth/me", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: 1,
        email: "demo@layout.test",
        role: "admin",
        first_name: "Demo",
        last_name: "Coder",
      }),
    })
  );
  await context.route("**/api/auth/refresh", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ access_token: "test-layout-token" }),
    })
  );

  // Patient core endpoints — minimal payloads sufficient for the sticky
  // header + metric strip to render without throwing.
  await context.route(/\/api\/patients\/3$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: 3,
        pid: 3,
        fname: "Alex",
        lname: "Rivera",
        DOB: "1955-03-14",
        sex: "Male",
        mrn: "MRN-00003",
      }),
    })
  );
  await context.route(/\/api\/patients\/3\/.*/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({}),
    })
  );
  await context.route(/\/api\/raf\/.*/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({}),
    })
  );

  // Suppress the first-run setup wizard so the patient page is the only
  // surface in the screenshot.
  await context.addInitScript(() => {
    try {
      window.localStorage.setItem("raf_onboarding_complete", "true");
    } catch { /* sandboxed storage */ }
  });
}

test.describe("Patient detail — mobile/tablet point-of-care", () => {
  test("renders cleanly at 414×896 (phone)", async ({ page, context, baseURL }) => {
    await seedAuth(context, baseURL ?? "http://localhost:3007");
    await page.setViewportSize({ width: 414, height: 896 });
    await page.goto(`/patients/${PATIENT_ID}`);

    await page.waitForSelector(".patient-name-h1", { timeout: 45_000 });
    // Let async card loads + fonts settle so the screenshot is stable.
    await page.waitForLoadState("networkidle").catch(() => undefined);

    await page.screenshot({
      path: "/tmp/patient-mobile.png",
      fullPage: true,
    });

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth
    );
    expect(overflow).toBeLessThanOrEqual(2);

    // Spec: H1 reduces 24 → 18px under 640px viewport.
    const fontPx = await page.evaluate(() => {
      const h1 = document.querySelector(".patient-name-h1") as HTMLElement | null;
      return h1 ? parseFloat(getComputedStyle(h1).fontSize) : 0;
    });
    expect(fontPx).toBeLessThanOrEqual(20);
    expect(fontPx).toBeGreaterThan(0);
  });

  test("renders cleanly at 768×1024 (tablet)", async ({ page, context, baseURL }) => {
    await seedAuth(context, baseURL ?? "http://localhost:3007");
    await page.setViewportSize({ width: 768, height: 1024 });
    await page.goto(`/patients/${PATIENT_ID}`);

    await page.waitForSelector(".patient-name-h1", { timeout: 45_000 });
    await page.waitForLoadState("networkidle").catch(() => undefined);

    await page.screenshot({
      path: "/tmp/patient-tablet.png",
      fullPage: true,
    });

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth
    );
    expect(overflow).toBeLessThanOrEqual(2);
  });
});
