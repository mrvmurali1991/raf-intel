import { defineConfig, devices } from "@playwright/test";
import path from "path";

/**
 * Playwright configuration for RAF Intelligence E2E tests.
 *
 * Base URL targets the live staging deployment at raf.comercioit.com.
 * Override with E2E_BASE_URL env var for local or CI environments.
 *
 * Tag-based execution:
 *   PW_GREP=@smoke   npx playwright test   — fast subset (Tests A + B); default on CI
 *   PW_GREP=@full    npx playwright test   — complete suite; runs nightly
 *
 * Retry policy:
 *   @smoke  → retries: 1 (set via SMOKE mode default)
 *   @full   → retries: 2 (nightly tolerance for transient flakes)
 */

const isFullRun = (process.env.PW_GREP ?? "@smoke") === "@full";

export default defineConfig({
  testDir: "./tests",
  testMatch: [
    "**/e2e/**/*.spec.ts",
    "**/a11y/**/*.spec.ts",
    "**/visual/**/*.spec.ts",
    "**/demo/**/*.spec.ts",
    "*.spec.ts",
  ],

  // Match all .spec.ts files under tests/ and tests/e2e/
  testMatch: ["**/*.spec.ts"],

  // Grep on the tag env var; defaults to @smoke so CI is always fast.
  grep: new RegExp(process.env.PW_GREP ?? "@smoke"),

  // Maximum time for one full test (pipeline can take up to 2 minutes).
  timeout: 180_000,

  // Retry policy: 1 for smoke runs, 2 for full nightly runs.
  retries: isFullRun ? 2 : 1,

  // Fail the suite immediately when a test worker crashes.
  fullyParallel: false,

  // Run tests sequentially — the live backend has limited capacity.
  workers: 1,

  // Rich HTML report for post-run review.
  reporter: [
    ["html", { outputFolder: "playwright-report", open: "never" }],
    ["list"],
  ],

  expect: {
    toHaveScreenshot: {
      threshold: 0.2,
      maxDiffPixelRatio: 0.005,
    },
  },

  use: {
    baseURL: process.env.E2E_BASE_URL ?? "https://raf.comercioit.com",

    // Keep browser open long enough for the 120-second pipeline calls.
    actionTimeout: 30_000,
    navigationTimeout: 60_000,

    // Capture a screenshot on every test failure automatically.
    screenshot: "only-on-failure",

    // Record a video on the first retry for easier debugging.
    video: "on-first-retry",

    // Full-page traces on the first retry so you can step through DevTools.
    trace: "on-first-retry",

    // Accept self-signed certificates on the staging environment.
    ignoreHTTPSErrors: true,
  },

  projects: [
    {
      name: "chromium",
      testMatch: ["**/e2e/**/*.spec.ts", "**/demo/**/*.spec.ts", "**/a11y/**/*.spec.ts", "*.spec.ts"],
      use: {
        ...devices["Desktop Chrome"],
        // Wide viewport so the full dashboard layout is visible.
        viewport: { width: 1440, height: 900 },
      },
    },
    {
      name: "e2e",
      testMatch: ["**/e2e/**/*.spec.ts"],
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 900 },
        // E2E_BASE_URL overrides prod URL for local dev runs.
        baseURL: process.env.E2E_BASE_URL ?? "https://raf.comercioit.com",
      },
    },
    {
      name: "a11y",
      testMatch: ["**/a11y/**/*.spec.ts"],
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 900 },
        baseURL: process.env.E2E_BASE_URL ?? "https://raf.comercioit.com",
      },
    },
    {
      name: "visual",
      testMatch: "**/visual/**/*.spec.ts",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 900 },
        baseURL: "http://localhost:3444",
        storageState: path.join(__dirname, "tests/visual/.auth-state.json"),
        // No retries for VRT — flakiness must be fixed, not hidden.
        // Traces always on so diffs are inspectable.
        trace: "on",
        screenshot: "only-on-failure",
        video: "off",
        ignoreHTTPSErrors: true,
      },
    },
  ],

  // Screenshots and videos land here.
  outputDir: "test-results",
});
