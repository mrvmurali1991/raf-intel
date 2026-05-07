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

/** When set to "1", annotatedShot always overwrites existing PNGs. */
export const DEMO_REGENERATE = process.env.DEMO_REGENERATE === "1";

// demo-shots lives NEXT TO playwright-report (not inside it) so the HTML
// reporter does not wipe it when it rebuilds playwright-report/ on each run.
export const SHOT_DIR = path.resolve(
  __dirname,
  "../../demo-shots"
);
export const STATE_FILE = path.resolve(__dirname, ".demo-auth-state.json");

// ``DEMO_PAUSE_MS`` controls the dwell time before each screenshot.  Bump
// this for slow-motion live screen-shares, drop it for headless CI runs.
export const PAUSE_MS = Number(process.env.DEMO_PAUSE_MS ?? "1500");

// ---------------------------------------------------------------------------
// Scene metadata — used by storyboard generator
// ---------------------------------------------------------------------------

export interface SceneMeta {
  /** Short file-name prefix, e.g. "01-worklist-annotated" */
  file: string;
  /** One-line caption for the tile border. */
  caption: string;
  /** Scene number 1-based. */
  scene: number;
}

/** Registry populated as shots are captured — storyboard reads this. */
export const SCENE_REGISTRY: SceneMeta[] = [];

/** Register a scene for the storyboard grid. */
export function registerScene(meta: SceneMeta): void {
  SCENE_REGISTRY.push(meta);
}

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
 * null if none matched).  Use this instead of ``waitForLoadState`` --
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

  // Honour DEMO_REGENERATE: skip if file already exists and flag is off.
  if (!DEMO_REGENERATE && fs.existsSync(file)) {
    status(`shot (cached) -> ${file}`);
    return file;
  }

  if (opts.highlight) {
    await opts.highlight.scrollIntoViewIfNeeded();
    await applyHighlight(page, opts.highlight);
  }

  await page.waitForTimeout(dwell);
  await page.screenshot({ path: file, fullPage: opts.fullPage ?? false });
  status(`shot -> ${file}`);

  if (opts.highlight) {
    await clearHighlight(page);
  }
  return file;
}

/** Annotated screenshot options. */
export interface AnnotatedShotOpts {
  /** One-line caption to burn into the highlight overlay. */
  caption?: string;
  /** Scene number for storyboard registration. */
  sceneNum?: number;
  /** Short storyboard caption for the tile border. */
  storyCaption?: string;
}

/** Annotated screenshot: tries each candidate locator until one is
 * visible, highlights it with an enhanced overlay (thicker border,
 * shadow, optional caption), snaps with name+`-annotated` suffix.
 *
 * When ``DEMO_REGENERATE=1`` the file is always rewritten even if it
 * already exists on disk. */
export async function annotatedShot(
  page: Page,
  name: string,
  candidates: Locator[],
  opts: AnnotatedShotOpts = {},
): Promise<string | null> {
  const file = path.join(SHOT_DIR, `${name}-annotated.png`);

  // Skip re-capture when file exists and regenerate flag is off.
  if (!DEMO_REGENERATE && fs.existsSync(file)) {
    status(`annotatedShot (cached) -> ${file}`);
    if (opts.sceneNum !== undefined && opts.storyCaption) {
      registerScene({ file: `${name}-annotated`, caption: opts.storyCaption, scene: opts.sceneNum });
    }
    return file;
  }

  for (const loc of candidates) {
    if (await loc.count()) {
      try {
        await loc.first().waitFor({ state: "visible", timeout: 4000 });
        const result = await shot(page, `${name}-annotated`, {
          highlight: loc.first(),
        });
        if (opts.caption) {
          await applyCaption(page, loc.first(), opts.caption);
          // Re-snap with the caption rendered.
          await page.waitForTimeout(300);
          ensureDir(SHOT_DIR);
          await page.screenshot({ path: file, fullPage: false });
          await clearCaption(page);
          status(`annotatedShot+caption -> ${file}`);
        }
        if (opts.sceneNum !== undefined && opts.storyCaption) {
          registerScene({ file: `${name}-annotated`, caption: opts.storyCaption, scene: opts.sceneNum });
        }
        return result;
      } catch {
        // try next candidate
      }
    }
  }
  status(`annotatedShot ${name}: no candidates matched, skipping`);
  // Still register with a placeholder path so the storyboard grid is consistent.
  if (opts.sceneNum !== undefined && opts.storyCaption) {
    registerScene({ file: `${name}`, caption: opts.storyCaption, scene: opts.sceneNum });
  }
  return null;
}

// ---------------------------------------------------------------------------
// Highlight + caption DOM helpers
// ---------------------------------------------------------------------------

async function applyHighlight(page: Page, loc: Locator): Promise<void> {
  const box = await loc.boundingBox();
  if (!box) return;
  await page.evaluate(
    ({ x, y, w, h }) => {
      const el = document.createElement("div");
      el.id = "__demo_highlight";
      el.style.cssText = [
        `position: fixed`,
        `left: ${x - 8}px`,
        `top: ${y - 8}px`,
        `width: ${w + 16}px`,
        `height: ${h + 16}px`,
        `border: 5px solid #DC2626`,
        `border-radius: 10px`,
        `box-shadow: 0 0 0 3px rgba(220,38,38,0.35), 0 0 0 9999px rgba(15,23,42,0.22), 0 6px 24px rgba(220,38,38,0.45)`,
        `z-index: 99999`,
        `pointer-events: none`,
      ].join(";");
      document.body.appendChild(el);

      const style = document.createElement("style");
      style.id = "__demo_highlight_style";
      style.textContent = "";
      document.head.appendChild(style);
    },
    { x: box.x, y: box.y, w: box.width, h: box.height },
  );
}

async function applyCaption(page: Page, loc: Locator, caption: string): Promise<void> {
  const box = await loc.boundingBox();
  if (!box) return;
  await page.evaluate(
    ({ x, y, w, h, text }) => {
      const tag = document.createElement("div");
      tag.id = "__demo_caption";
      const maxW = Math.max(w + 16, 260);
      tag.style.cssText = [
        `position: fixed`,
        `left: ${x - 8}px`,
        `top: ${y + h + 12}px`,
        `max-width: ${maxW}px`,
        `background: #DC2626`,
        `color: #ffffff`,
        `font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif`,
        `font-size: 13px`,
        `font-weight: 600`,
        `line-height: 1.4`,
        `padding: 6px 12px`,
        `border-radius: 6px`,
        `box-shadow: 0 4px 12px rgba(0,0,0,0.35)`,
        `z-index: 100000`,
        `pointer-events: none`,
        `white-space: pre-line`,
        `letter-spacing: 0.01em`,
      ].join(";");
      tag.textContent = text;
      document.body.appendChild(tag);
    },
    { x: box.x, y: box.y, w: box.width, h: box.height, text: caption },
  );
}

async function clearHighlight(page: Page): Promise<void> {
  await page.evaluate(() => {
    document.getElementById("__demo_highlight")?.remove();
    document.getElementById("__demo_highlight_style")?.remove();
  });
}

async function clearCaption(page: Page): Promise<void> {
  await page.evaluate(() => {
    document.getElementById("__demo_caption")?.remove();
  });
}

// ---------------------------------------------------------------------------
// Storyboard composite generator (3x3 grid, 9 scenes)
// ---------------------------------------------------------------------------

/**
 * Build a single storyboard.png that tiles every scene screenshot in a
 * 3x3 grid.  Each tile includes a scene-number badge and a 1-line
 * caption in its bottom border.
 *
 * Requires the ``sharp`` package (already in node_modules).
 */
export async function generateStoryboard(
  scenes: SceneMeta[],
  outputPath: string,
): Promise<void> {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const sharp = require("sharp") as typeof import("sharp");

  const COLS = 3;
  const TILE_W = 640;
  const TILE_H = 400;
  const CAPTION_H = 48;
  const BORDER = 4;

  const FULL_TILE_H = TILE_H + CAPTION_H;
  const GRID_W = COLS * TILE_W + (COLS + 1) * BORDER;

  // Sort scenes by scene number.
  const sorted = [...scenes].sort((a, b) => a.scene - b.scene);

  // Always produce a 3x3 grid; pad with placeholder grey tiles if < 9.
  const TOTAL = 9;
  while (sorted.length < TOTAL) {
    sorted.push({ file: "", caption: "(no screenshot)", scene: sorted.length + 1 });
  }

  const ROWS = Math.ceil(TOTAL / COLS);
  const GRID_H = ROWS * FULL_TILE_H + (ROWS + 1) * BORDER;

  // Create blank canvas (dark background).
  const canvas = sharp({
    create: {
      width: GRID_W,
      height: GRID_H,
      channels: 3,
      background: { r: 15, g: 23, b: 42 },
    },
  });

  const compositeInputs: import("sharp").OverlayOptions[] = [];

  for (let i = 0; i < TOTAL; i++) {
    const meta = sorted[i];
    const col = i % COLS;
    const row = Math.floor(i / COLS);
    const tileX = BORDER + col * (TILE_W + BORDER);
    const tileY = BORDER + row * (FULL_TILE_H + BORDER);

    // Build scene thumbnail.
    let thumbBuf: Buffer;
    const filePath = path.join(SHOT_DIR, `${meta.file}.png`);
    if (meta.file && fs.existsSync(filePath)) {
      thumbBuf = await sharp(filePath)
        .resize(TILE_W, TILE_H, { fit: "cover", position: "top" })
        .toBuffer();
    } else {
      thumbBuf = await sharp({
        create: {
          width: TILE_W,
          height: TILE_H,
          channels: 3,
          background: { r: 30, g: 41, b: 59 },
        },
      }).png().toBuffer();
    }

    compositeInputs.push({ input: thumbBuf, top: tileY, left: tileX });

    // Caption strip rendered as SVG.
    const sceneLabel = `Scene ${meta.scene}`;
    const captionText = meta.caption.length > 68
      ? meta.caption.slice(0, 65) + "..."
      : meta.caption;

    const captionSvg = Buffer.from(
      `<svg xmlns="http://www.w3.org/2000/svg" width="${TILE_W}" height="${CAPTION_H}">` +
      `<rect width="${TILE_W}" height="${CAPTION_H}" fill="#0F172A"/>` +
      `<rect width="64" height="${CAPTION_H}" fill="#DC2626"/>` +
      `<text x="32" y="${Math.floor(CAPTION_H / 2) + 6}" ` +
        `font-family="monospace" font-size="13" font-weight="bold" ` +
        `fill="#ffffff" text-anchor="middle" dominant-baseline="middle">` +
        `${sceneLabel}</text>` +
      `<text x="76" y="${Math.floor(CAPTION_H / 2) + 6}" ` +
        `font-family="-apple-system, sans-serif" font-size="12" ` +
        `fill="#CBD5E1" dominant-baseline="middle" text-anchor="start">` +
        `${captionText}</text>` +
      `</svg>`
    );

    const captionBuf = await sharp(captionSvg).png().toBuffer();
    compositeInputs.push({ input: captionBuf, top: tileY + TILE_H, left: tileX });
  }

  await canvas
    .composite(compositeInputs)
    .png({ compressionLevel: 8 })
    .toFile(outputPath);

  status(`storyboard -> ${outputPath}`);
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
        `dashboard/stats returned ${stats.status()} -- auth may be misconfigured`,
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
      "EMR is not connected -- /worklist will show the onboarding flow.  " +
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
      "Zero patients / gaps / suspects -- the storyboard will show empty states.  " +
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
    console.log(`    NOTE  ${note}`);
  }
}

// ---------------------------------------------------------------------------
// Scene assertions
// ---------------------------------------------------------------------------

export async function softAssertVisible(
  loc: Locator,
  description: string,
): Promise<void> {
  try {
    await expect(loc).toBeVisible({ timeout: 8000 });
  } catch {
    status(`SOFT-FAIL  ${description} not visible -- value-prop missing on this scene`);
  }
}
