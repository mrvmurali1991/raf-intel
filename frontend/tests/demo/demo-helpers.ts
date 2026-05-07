/**
 * Shared utilities for the live RAF Intelligence sales demo.
 *
 * The goal of every helper here is to make the demo recording stable
 * regardless of the data state on the local stack — if a scene cannot
 * find the content it expects, the helper prints an actionable
 * remediation message and continues so we still produce SOME storyboard
 * for the presenter to review.
 */
import { type Page, type Locator, expect } from "@playwright/test";
import * as path from "path";
import * as fs from "fs";

// ---------------------------------------------------------------------------
// Configuration (env-overridable)
// ---------------------------------------------------------------------------

export const BASE_URL = process.env.BASE_URL ?? "http://localhost:3444";
export const API_URL = process.env.API_URL ?? "http://localhost:8500";
export const EMAIL = process.env.DEMO_EMAIL ?? "admin@raf.health";
export const PASSWORD = process.env.DEMO_PASSWORD ?? "Admin@123";

export const SHOT_DIR = path.resolve(
  __dirname,
  "../../playwright-report/demo-shots"
);
export const STATE_FILE = path.resolve(__dirname, ".demo-auth-state.json");

// ``DEMO_PAUSE_MS`` controls the dwell time before each screenshot.  Bump
// this for slow-motion live screen-shares, drop it for headless CI runs.
export const PAUSE_MS = Number(process.env.DEMO_PAUSE_MS ?? "1500");

// ---------------------------------------------------------------------------
// Filesystem helpers
// ---------------------------------------------------------------------------

export function ensureDir(dir: string): void {
  fs.mkdirSync(dir, { recursive: true });
}

// ---------------------------------------------------------------------------
// Narration — printed to stdout so the presenter can read along
// ---------------------------------------------------------------------------

export function narrate(scene: string, line: string): void {
  // eslint-disable-next-line no-console
  console.log(`\n  [${scene}] ${line}`);
}

export function status(line: string): void {
  // eslint-disable-next-line no-console
  console.log(`        … ${line}`);
}

// ---------------------------------------------------------------------------
// Auth flow
// ---------------------------------------------------------------------------

/** Programmatic login via the API: faster + avoids the auth rate-limiter
 * that locks the admin account after 5 fresh UI logins.  Sets the same
 * cookies a real browser login would set (refresh-token + authenticated)
 * so the auth-context boots cleanly on the first real page navigation.
 *
 * Called once in ``beforeAll`` and the resulting cookies are persisted
 * via ``page.context().storageState`` to STATE_FILE — every scene then
 * loads that file via the project ``use.storageState`` config.
 */
export async function loginViaApi(page: Page): Promise<void> {
  const resp = await page.request.post(`${API_URL}/api/auth/login`, {
    data: { email: EMAIL, password: PASSWORD },
  });
  if (!resp.ok()) {
    const body = await resp.text();
    throw new Error(`Login failed: ${resp.status()} ${body.slice(0, 200)}`);
  }
  const body = await resp.json();
  // Stash the access token for diagnostic use; the auth-context will
  // refresh into its own copy via the httpOnly refresh cookie that
  // ``page.request.post`` already accepted into the browser context.
  await page.addInitScript((token: string) => {
    (window as unknown as { __demoAccessToken?: string }).__demoAccessToken = token;
  }, body.access_token);
}

/** Save the current page's browser context cookies to disk so that
 * later pages opened with ``storageState: STATE_FILE`` reuse the auth
 * session.  Returns the path written. */
export async function saveAuthState(page: Page): Promise<string> {
  await page.context().storageState({ path: STATE_FILE });
  return STATE_FILE;
}

/** Read STATE_FILE if present.  Returned shape is whatever Playwright
 * wrote — used by readiness probe to verify auth was actually saved. */
export function authStateExists(): boolean {
  return fs.existsSync(STATE_FILE);
}

/** Cached UI login: only used as a fallback if API login fails. */
export async function loginViaUi(page: Page): Promise<void> {
  await page.goto(`${BASE_URL}/login`);
  await page.waitForSelector('input[type="email"]', { state: "visible" });
  await page.fill('input[type="email"]', EMAIL);
  await page.fill('input[type="password"]', PASSWORD);
  await page.click('button[type="submit"]');
  await page.waitForURL((u) => !u.pathname.startsWith("/login"), {
    timeout: 30_000,
  });
}

/** Returns true if the auth-context resolved a user; false if we're
 * stuck on the login page or the spinner.  A presenter should treat
 * false as "the storyboard for that scene will be unusable, fix data
 * first". */
export async function authResolved(page: Page): Promise<boolean> {
  if (page.url().includes("/login")) return false;
  // The sidebar's "Dashboard" link only mounts after auth-context
  // settles — its presence is the cleanest signal.
  try {
    await page
      .getByRole("link", { name: /Dashboard|Today's worklist/i })
      .first()
      .waitFor({ timeout: 15_000 });
    return true;
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Content readiness
// ---------------------------------------------------------------------------

/** Wait for the FIRST visible match from a list of candidate text
 * fragments, with sensible timeout, and return the matched locator (or
 * null if none matched).  Use this instead of ``waitForLoadState`` —
 * React Query keeps the network busy with refetches so ``networkidle``
 * never fires reliably. */
export async function waitForFirst(
  page: Page,
  candidates: string[],
  timeoutMs: number = 12_000,
): Promise<Locator | null> {
  const deadline = Date.now() + timeoutMs;
  for (const text of candidates) {
    const remaining = Math.max(500, deadline - Date.now());
    try {
      const loc = page.getByText(text, { exact: false }).first();
      await loc.waitFor({ state: "visible", timeout: remaining });
      return loc;
    } catch {
      // try the next candidate
    }
  }
  return null;
}

/** True if every text fragment is present on the page (any visible
 * occurrence counts).  Used by the data-readiness probe. */
export async function hasAllText(
  page: Page,
  fragments: string[],
): Promise<boolean> {
  for (const f of fragments) {
    const count = await page.getByText(f, { exact: false }).count();
    if (count === 0) return false;
  }
  return true;
}

// ---------------------------------------------------------------------------
// Screenshot capture
// ---------------------------------------------------------------------------

interface ShotOpts {
  /** Capture full scrolled page, not just the viewport. */
  fullPage?: boolean;
  /** Optional element to highlight with a red overlay before snapping. */
  highlight?: Locator;
  /** Override the dwell time before snapping. */
  dwellMs?: number;
}

/** Settle the page (small dwell) and snap.  Optionally apply a red
 * highlight box around an element so the storyboard reader knows what
 * to look at. */
export async function shot(
  page: Page,
  name: string,
  opts: ShotOpts = {},
): Promise<string> {
  ensureDir(SHOT_DIR);
  const file = path.join(SHOT_DIR, `${name}.png`);
  const dwell = opts.dwellMs ?? PAUSE_MS;

  if (opts.highlight) {
    await opts.highlight.scrollIntoViewIfNeeded();
    await applyHighlight(page, opts.highlight);
  }

  await page.waitForTimeout(dwell);
  await page.screenshot({ path: file, fullPage: opts.fullPage ?? false });
  status(`shot → ${file}`);

  if (opts.highlight) {
    await clearHighlight(page);
  }
  return file;
}

/** Annotated screenshot: tries each candidate locator until one is
 * visible, highlights it, snaps with name+`-annotated` suffix.  Useful
 * for "the proof point of this scene is THIS specific tile". */
export async function annotatedShot(
  page: Page,
  name: string,
  candidates: Locator[],
): Promise<string | null> {
  for (const loc of candidates) {
    if (await loc.count()) {
      try {
        await loc.first().waitFor({ state: "visible", timeout: 4000 });
        return await shot(page, `${name}-annotated`, {
          highlight: loc.first(),
        });
      } catch {
        // try next candidate
      }
    }
  }
  status(`annotatedShot ${name}: no candidates matched, skipping`);
  return null;
}

async function applyHighlight(page: Page, loc: Locator): Promise<void> {
  const box = await loc.boundingBox();
  if (!box) return;
  await page.evaluate(
    ({ x, y, w, h }) => {
      const el = document.createElement("div");
      el.id = "__demo_highlight";
      el.style.cssText = `
        position: fixed;
        left: ${x - 6}px;
        top: ${y - 6}px;
        width: ${w + 12}px;
        height: ${h + 12}px;
        border: 3px solid #DC2626;
        border-radius: 8px;
        box-shadow: 0 0 0 9999px rgba(15, 23, 42, 0.18);
        z-index: 99999;
        pointer-events: none;
        animation: __demo_pulse 1.2s ease-in-out 1;
      `;
      const style = document.createElement("style");
      style.id = "__demo_highlight_style";
      style.textContent = `
        @keyframes __demo_pulse {
          0%   { box-shadow: 0 0 0 9999px rgba(15, 23, 42, 0.30); }
          100% { box-shadow: 0 0 0 9999px rgba(15, 23, 42, 0.18); }
        }
      `;
      document.head.appendChild(style);
      document.body.appendChild(el);
    },
    { x: box.x, y: box.y, w: box.width, h: box.height },
  );
}

async function clearHighlight(page: Page): Promise<void> {
  await page.evaluate(() => {
    document.getElementById("__demo_highlight")?.remove();
    document.getElementById("__demo_highlight_style")?.remove();
  });
}

// ---------------------------------------------------------------------------
// Data-readiness pre-flight
// ---------------------------------------------------------------------------

export interface DataReadiness {
  emr_connected: boolean;
  patients_total: number;
  open_recapture_gaps: number;
  total_suspects_open: number;
  notes: string[];
}

/** Probe the API for whether enough data is loaded for a buyer-grade
 * demo.  Use the result to decide whether each scene is going to
 * actually show value or just an onboarding screen. */
export async function probeDataReadiness(
  page: Page,
): Promise<DataReadiness> {
  const notes: string[] = [];
  const result: DataReadiness = {
    emr_connected: false,
    patients_total: 0,
    open_recapture_gaps: 0,
    total_suspects_open: 0,
    notes,
  };

  try {
    const stats = await page.request.get(`${API_URL}/api/dashboard/stats`);
    if (stats.ok()) {
      const body = (await stats.json()) as Record<string, unknown>;
      result.patients_total =
        typeof body.total_patients === "number" ? body.total_patients : 0;
      result.open_recapture_gaps =
        typeof body.open_recapture_gaps === "number"
          ? body.open_recapture_gaps
          : 0;
      result.total_suspects_open =
        typeof body.total_suspects_open === "number"
          ? body.total_suspects_open
          : 0;
    } else {
      notes.push(
        `dashboard/stats returned ${stats.status()} — auth may be misconfigured`,
      );
    }
  } catch (e) {
    notes.push(`dashboard/stats failed: ${(e as Error).message}`);
  }

  try {
    const emr = await page.request.get(`${API_URL}/api/emr/status`);
    if (emr.ok()) {
      const body = (await emr.json()) as { connected?: boolean };
      result.emr_connected = !!body.connected;
    }
  } catch {
    notes.push("emr/status unreachable");
  }

  if (!result.emr_connected) {
    notes.push(
      "EMR is not connected — /worklist will show the onboarding flow.  " +
        "POST /api/emr/demo-connect (or click 'Connect Demo EMR' on /emr-config) " +
        "to populate patients, gaps, and suspects.",
    );
  }
  if (
    result.patients_total === 0 &&
    result.open_recapture_gaps === 0 &&
    result.total_suspects_open === 0
  ) {
    notes.push(
      "Zero patients / gaps / suspects — the storyboard will show empty states.  " +
        "Run the seed scripts then re-run the demo.",
    );
  }

  return result;
}

export function logReadiness(r: DataReadiness): void {
  // eslint-disable-next-line no-console
  console.log(
    `  Data readiness: emr=${r.emr_connected} patients=${r.patients_total} ` +
      `gaps=${r.open_recapture_gaps} suspects=${r.total_suspects_open}`,
  );
  for (const note of r.notes) {
    // eslint-disable-next-line no-console
    console.log(`    ⚠  ${note}`);
  }
}

// ---------------------------------------------------------------------------
// Scene assertions — used by the demo to fail fast when a critical
// piece of UI is missing (e.g. the AuditReadinessCard didn't render at
// all because the IRR endpoint 500ed).  Soft-fails: if the assertion
// fails the storyboard still gets the screenshot, but we log a clear
// "this scene's value-prop is broken" line so the presenter knows.
// ---------------------------------------------------------------------------

export async function softAssertVisible(
  loc: Locator,
  description: string,
): Promise<void> {
  try {
    await expect(loc).toBeVisible({ timeout: 8000 });
  } catch {
    status(`SOFT-FAIL  ${description} not visible — value-prop missing on this scene`);
  }
}
