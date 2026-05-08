import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright config for the 60-second sales demo video recording.
 * Outputs 1920x1080 WebM via Chromium, then convert to MP4 with ffmpeg.
 *
 * Run:
 *   cd frontend && npx playwright test --config=playwright.video.config.ts \
 *     demo-video/record-demo.spec.ts --headed=false
 */
export default defineConfig({
  testDir: "./",
  timeout: 300_000,
  retries: 0,
  workers: 1,
  fullyParallel: false,
  testIgnore: [],

  reporter: [
    ["html", { outputFolder: "playwright-report", open: "never" }],
    ["list"],
  ],

  use: {
    baseURL: "http://localhost:3444",
    actionTimeout: 60_000,
    navigationTimeout: 60_000,
    ignoreHTTPSErrors: true,
    video: "on",
    screenshot: "off",
    trace: "off",
  },

  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1920, height: 1080 },
        launchOptions: {
          args: ["--window-size=1920,1080"],
        },
      },
    },
  ],

  outputDir: "test-results",
});
