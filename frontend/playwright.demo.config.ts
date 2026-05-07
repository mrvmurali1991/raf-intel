import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright config for the live sales/investor demo.
 *
 * Targets the local Docker stack (http://localhost:3444) by default.
 * Override with the BASE_URL env var if you want to record a demo
 * against a staging or pilot environment.
 *
 * Outputs an HTML report and screenshot storyboard you can drop
 * directly into a deck.
 */
export default defineConfig({
  testDir: "./tests/demo",
  timeout: 180_000,
  fullyParallel: false,
  retries: 0,
  workers: 1,
  testIgnore: ["**/global-setup.ts"],
  globalSetup: "./tests/demo/global-setup.ts",

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
    trace: "off",
  },

  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 900 },
        storageState: "./tests/demo/.demo-auth-state.json",
      },
    },
  ],
});
