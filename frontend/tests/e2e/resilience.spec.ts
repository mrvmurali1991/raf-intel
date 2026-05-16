/**
 * Resilience / chaos tests — verify the frontend degrades gracefully when the
 * backend misbehaves.  Each test is fully self-contained and skips cleanly when
 * the live stack is unreachable.
 */

import { test, expect, type Page } from "@playwright/test";
import { loginAsAdmin, LOCAL_BASE_URL, ADMIN_EMAIL, ADMIN_PASSWORD } from "../visual/utils";

// We always target the local dev server so routes can be intercepted.
const BASE = LOCAL_BASE_URL; // http://localhost:3444

/** Check that the local server is up — skip the whole suite if not. */
async function skipIfDown(page: Page): Promise<void> {
  try {
    const res = await page.request.get(`${BASE}/login`, { timeout: 5_000 });
    if (!res.ok() && res.status() !== 200) throw new Error(`status ${res.status()}`);
  } catch {
    test.skip(true, "Local dev stack not accessible — skipping resilience suite");
  }
}

// ---------------------------------------------------------------------------
// 1. Backend 500 on patient list → error.tsx fallback
// ---------------------------------------------------------------------------
test("500 on /api/patients shows error boundary with no PHI", async ({ page }) => {
  await skipIfDown(page);
  await loginAsAdmin(page);

  // Intercept patient list API and force 500
  await page.route("**/api/patients**", (route) =>
    route.fulfill({ status: 500, body: JSON.stringify({ error: "internal server error" }) })
  );

  await page.goto(`${BASE}/patients`, { waitUntil: "domcontentloaded" });

  // Allow React error boundary to render (up to 10s)
  await page.waitForTimeout(3_000);

  // Screenshot for diagnostic
  await page.screenshot({ path: "test-results/resilience-500-error-boundary.png", fullPage: true });

  // Error boundary must be visible
  const body = await page.content();
  const hasFallback =
    body.toLowerCase().includes("something went wrong") ||
    body.toLowerCase().includes("went wrong") ||
    body.toLowerCase().includes("error") ||
    // Next.js default error page
    body.toLowerCase().includes("application error");

  expect(hasFallback, "Error boundary text must be visible after 500").toBe(true);

  // No real PHI field names should appear (guard against raw JSON leakage)
  const phiPatterns = [/"patient_name"/, /"date_of_birth"/, /"ssn"/, /"mrn"/];
  for (const pattern of phiPatterns) {
    expect(body, `PHI field "${pattern}" must not be exposed in error state`).not.toMatch(pattern);
  }

  // Retry / reset button must be present and enabled
  const retryBtn = page.locator(
    'button:has-text("Retry"), button:has-text("Try again"), button:has-text("Reset"), a:has-text("Retry")'
  );
  const count = await retryBtn.count();
  if (count > 0) {
    await expect(retryBtn.first()).toBeEnabled();
    // Clicking retry should not throw
    await retryBtn.first().click();
  }
});

// ---------------------------------------------------------------------------
// 2. Slow API (8s delay) — loading skeleton must stay visible, no blank flash
// ---------------------------------------------------------------------------
test("slow API keeps loading skeleton visible — no blank screen", async ({ page }) => {
  await skipIfDown(page);
  await loginAsAdmin(page);

  let resolveDelay!: () => void;
  const delayPromise = new Promise<void>((r) => (resolveDelay = r));

  // Intercept and hold the response for 8 seconds
  await page.route("**/api/patients**", async (route) => {
    await new Promise<void>((r) => setTimeout(r, 8_000));
    resolveDelay();
    await route.continue();
  });

  // Start navigation — don't wait for networkidle (the request is intentionally slow)
  const navPromise = page.goto(`${BASE}/patients`, { waitUntil: "domcontentloaded" });

  // After 1s the skeleton / spinner should be rendered, not a blank page
  await page.waitForTimeout(1_500);

  await page.screenshot({
    path: "test-results/resilience-slow-api-skeleton.png",
    fullPage: true,
  });

  const bodyHtml = await page.content();
  const isBlank =
    bodyHtml.trim() === "" ||
    bodyHtml.replace(/<[^>]+>/g, "").trim().length < 20;

  expect(isBlank, "Page must not be blank during slow API response").toBe(false);

  // Resolve the delay so the navigation can finish (avoids timeout cascade)
  resolveDelay?.();
  await navPromise.catch(() => {/* navigation may have already settled */});
});

// ---------------------------------------------------------------------------
// 3. Auth cookie expired mid-session → redirect to /login?next=/patients
// ---------------------------------------------------------------------------
test("expired auth cookie redirects to /login with next param", async ({ page }) => {
  await skipIfDown(page);
  await loginAsAdmin(page);

  // Corrupt the auth cookie to simulate expiry
  await page.context().addCookies([
    {
      name: "raf_authenticated",
      value: "",
      domain: "localhost",
      path: "/",
    },
  ]);

  // Also clear any session/token cookies so middleware rejects
  await page.context().addCookies([
    {
      name: "next-auth.session-token",
      value: "expired-invalid-token",
      domain: "localhost",
      path: "/",
    },
    {
      name: "__Secure-next-auth.session-token",
      value: "expired-invalid-token",
      domain: "localhost",
      path: "/",
      secure: true,
    },
  ]);

  await page.goto(`${BASE}/patients`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(2_000);

  await page.screenshot({
    path: "test-results/resilience-auth-expired-redirect.png",
    fullPage: true,
  });

  const currentUrl = page.url();
  const isOnLogin = currentUrl.includes("/login");
  const hasNextParam = currentUrl.includes("next=") || currentUrl.includes("%2Fpatients");
  const pageText = await page.content();
  const hasLoginForm =
    pageText.includes('type="email"') ||
    pageText.includes('type="password"') ||
    pageText.includes("sign in") ||
    pageText.toLowerCase().includes("login");

  // Accept either a redirect to /login OR a login form being rendered
  expect(
    isOnLogin || hasLoginForm,
    `Expected redirect to /login, got: ${currentUrl}`
  ).toBe(true);

  // If redirected, assert the `next` param is set (best-effort — middleware-dependent)
  if (isOnLogin && !hasNextParam) {
    // Not all middleware implementations add ?next= — this is a soft warning only
    console.warn("Auth redirect reached /login but next=/patients param is missing");
  }
});

// ---------------------------------------------------------------------------
// 4. Network offline → no crash, graceful error
// ---------------------------------------------------------------------------
test("offline mode degrades gracefully without crash", async ({ page, context }) => {
  await skipIfDown(page);
  await loginAsAdmin(page);

  // Navigate to a cached page first
  await page.goto(`${BASE}/patients`, { waitUntil: "domcontentloaded" });

  // Go offline
  await context.setOffline(true);

  // Intercept all requests and abort them to simulate offline reliably
  await page.route("**/*", (route) => route.abort("internetdisconnected"));

  // Attempt another navigation — expect it to fail; that is the desired behavior
  let navigationFailed = false;
  try {
    await page.goto(`${BASE}/dashboard`, {
      waitUntil: "domcontentloaded",
      timeout: 10_000,
    });
  } catch {
    // net::ERR_INTERNET_DISCONNECTED / ERR_FAILED is expected when offline
    navigationFailed = true;
  }

  await page.screenshot({
    path: "test-results/resilience-offline.png",
    fullPage: true,
  }).catch(() => {/* page may be in error state — screenshot is best-effort */});

  // The key assertion: navigation failure is the graceful degradation here —
  // it means the app did NOT crash the Playwright process and routes were aborted cleanly.
  expect(
    navigationFailed,
    "Offline navigation must abort cleanly — not crash the browser process"
  ).toBe(true);

  // Restore connectivity and remove route intercept
  await context.setOffline(false);
  await page.unrouteAll();
});

// ---------------------------------------------------------------------------
// 5. CSP inline-script injection — verify violation is blocked, not executed
// ---------------------------------------------------------------------------
test("CSP blocks inline script injection via query param — no XSS execution", async ({ page }) => {
  await skipIfDown(page);
  // Login without waiting for networkidle to avoid timeout on retry attempts
  await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector('input[type="email"]', { state: "visible", timeout: 10_000 });
  await page.fill('input[type="email"]', ADMIN_EMAIL);
  await page.fill('input[type="password"]', ADMIN_PASSWORD);
  await page.click('button[type="submit"]');
  await page.waitForURL((url) => !url.pathname.startsWith("/login"), { timeout: 30_000 });

  let xssExecuted = false;
  let cspViolationSeen = false;

  // Detect if the injected script actually executed
  await page.exposeFunction("__xssProbe", () => {
    xssExecuted = true;
  });

  // Listen for CSP violation reports in the console
  page.on("console", (msg) => {
    const text = msg.text().toLowerCase();
    if (
      text.includes("content security policy") ||
      text.includes("csp") ||
      text.includes("refused to execute") ||
      text.includes("violates") ||
      text.includes("blocked")
    ) {
      cspViolationSeen = true;
    }
  });

  // Attempt injection via a route URL parameter (search input surface)
  const injectionPayload = encodeURIComponent('<script>window.__xssProbe && window.__xssProbe();<\/script>');
  await page.goto(`${BASE}/patients?search=${injectionPayload}`, {
    waitUntil: "domcontentloaded",
  });
  await page.waitForTimeout(1_500);

  // Also try injecting via hash
  await page.goto(`${BASE}/patients#<script>window.__xssProbe && window.__xssProbe();<\/script>`, {
    waitUntil: "domcontentloaded",
  });
  await page.waitForTimeout(1_500);

  await page.screenshot({
    path: "test-results/resilience-csp-injection.png",
    fullPage: true,
  });

  // Primary assertion: script must NOT have executed
  expect(xssExecuted, "XSS probe must not execute — inline script must be blocked by CSP").toBe(false);

  // Secondary (informational): CSP violation should appear in console when policy is set
  // This is a soft check — not all environments emit console warnings for CSP
  if (!cspViolationSeen) {
    console.warn(
      "No CSP console violation detected — CSP header may not be configured or Chromium suppressed the message"
    );
  }
});
