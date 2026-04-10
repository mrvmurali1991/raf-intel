import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright configuration for RAF Intelligence E2E tests.
 *
 * Base URL targets the live staging deployment at raf.comercioit.com.
 * Tests run headed by default during local development; set CI=true to run
 * headless in pipelines.
 */
export default defineConfig({
  testDir: "./tests/e2e",

  // Maximum time for one full test (pipeline can take up to 2 minutes).
  timeout: 180_000,

  // Fail the suite immediately when a test worker crashes.
  fullyParallel: false,

  // Retry failed tests once to guard against transient network blips.
  retries: 1,

  // Run tests sequentially — the live backend has limited capacity.
  workers: 1,

  // Rich HTML report for post-run review.
  reporter: [
    ["html", { outputFolder: "playwright-report", open: "never" }],
    ["list"],
  ],

  use: {
    baseURL: "https://raf.comercioit.com",

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
      use: {
        ...devices["Desktop Chrome"],
        // Wide viewport so the full dashboard layout is visible.
        viewport: { width: 1440, height: 900 },
      },
    },
  ],

  // Screenshots and videos land here.
  outputDir: "test-results",
});
