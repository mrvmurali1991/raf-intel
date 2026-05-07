import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright config for the live sales / investor demo.
 *
 * Targets the local Docker stack (http://localhost:3444) by default.
 * Override BASE_URL for staging / pilot recordings.
 *
 * Useful env knobs (all optional):
 *   BASE_URL         — frontend URL          (default http://localhost:3444)
 *   API_URL          — backend URL           (default http://localhost:8500)
 *   DEMO_EMAIL       — login email           (default admin@raf.health)
 *   DEMO_PASSWORD    — login password        (default Admin@123)
 *   DEMO_PAUSE_MS    — dwell before snap     (default 1500)
 *   DEMO_VIDEO       — "1" to record video   (default off)
 *   DEMO_TRACE       — "1" to record trace   (default off)
 *   PWDEBUG_SLOWMO   — ms to slow each action (passed to launchOptions)
 *
 * Outputs an HTML report and screenshot storyboard you can drop
 * directly into a deck.
 */
const SLOWMO = Number(process.env.PWDEBUG_SLOWMO ?? "0");

export default defineConfig({
  testDir: "./tests/demo",
  timeout: 180_000,
  expect: { timeout: 12_000 },
  fullyParallel: false,
  retries: 0,
  workers: 1,
  testIgnore: ["**/global-setup.ts", "**/demo-helpers.ts"],

  reporter: [
    ["html", { outputFolder: "playwright-report", open: "never" }],
    ["list"],
  ],

  use: {
    baseURL: process.env.BASE_URL ?? "http://localhost:3444",
    actionTimeout: 30_000,
    navigationTimeout: 60_000,
    screenshot: "only-on-failure",
    video: process.env.DEMO_VIDEO === "1" ? "on" : "off",
    trace: process.env.DEMO_TRACE === "1" ? "on" : "off",
    launchOptions: {
      slowMo: SLOWMO,
    },
  },

  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 900 },
      },
    },
  ],
});
