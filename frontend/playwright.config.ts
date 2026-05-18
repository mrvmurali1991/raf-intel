import { defineConfig, devices } from "@playwright/test";
import path from "path";

/**
 * Playwright configuration for RAF Intelligence E2E tests.
 *
 * Base URL targets the live staging deployment at raf.comercioit.com by
 * default. Override with E2E_BASE_URL env var for local dev server runs.
 *
 * Run the new E2E suite:
 *   cd frontend && E2E_BASE_URL=http://localhost:3001 npx playwright test --project=e2e
 * Or use the helper script:
 *   bash frontend/scripts/e2e.sh
 */
export default defineConfig({
  testDir: "./tests",
  testMatch: [
    "**/e2e/**/*.spec.ts",
    "**/a11y/**/*.spec.ts",
    "**/visual/**/*.spec.ts",
    "**/demo/**/*.spec.ts",
    "*.spec.ts",
  ],

  // Maximum time for one full test (pipeline can take up to 2 minutes).
  timeout: 180_000,

  // Fail the suite immediately when a test worker crashes.
  fullyParallel: false,

  // Retry failed tests once to guard against transient network blips.
  retries: 1,

  // Two parallel workers for the local e2e suite; 1 for live staging.
  workers: process.env.E2E_BASE_URL ? 2 : 1,

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
