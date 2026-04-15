/**
 * playwright.config.ts
 *
 * Playwright E2E test configuration for RAF Intelligence.
 *
 * Tests target a running frontend (Next.js) and backend (FastAPI).
 * Set the following environment variables to point at a live environment:
 *
 *   PLAYWRIGHT_BASE_URL  — Frontend URL (default: http://localhost:3001)
 *   TEST_USERNAME        — Test user email (default: admin@raf.health)
 *   TEST_PASSWORD        — Test user password (default: Admin@123)
 */

import { defineConfig, devices } from "@playwright/test";

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || "http://localhost:3001";

export default defineConfig({
  // Directory containing spec files
  testDir: "./",

  // Glob patterns for test files
  testMatch: "**/*.spec.ts",

  // Run tests in parallel within each file
  fullyParallel: false,

  // Fail the build on CI if test.only() is accidentally left in code
  forbidOnly: !!process.env.CI,

  // Retry on CI to handle transient flakiness
  retries: process.env.CI ? 2 : 0,

  // Run 1 worker in CI for predictable resource usage
  workers: process.env.CI ? 1 : 2,

  // Global timeout per test
  timeout: 60_000,

  // Assertion timeout
  expect: {
    timeout: 10_000,
  },

  // Reporter configuration
  reporter: process.env.CI
    ? [["github"], ["html", { outputFolder: "playwright-report", open: "never" }]]
    : [["list"], ["html", { outputFolder: "playwright-report", open: "on-failure" }]],

  // Shared settings for all projects
  use: {
    baseURL: BASE_URL,

    // Capture screenshots, video, and trace on first retry
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    trace: "on-first-retry",

    // Viewport
    viewport: { width: 1280, height: 720 },

    // Authentication state file reused across tests
    storageState: "./e2e/.auth/user.json",
  },

  // Test projects — run against multiple browsers
  projects: [
    // Setup project — performs login and saves auth state
    {
      name: "setup",
      testMatch: "**/global-setup.ts",
      use: { storageState: undefined }, // no auth state for setup
    },

    // Chromium — main browser
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
      dependencies: ["setup"],
    },

    // Firefox — cross-browser
    {
      name: "firefox",
      use: { ...devices["Desktop Firefox"] },
      dependencies: ["setup"],
    },

    // Mobile viewport — Safari on iPhone
    {
      name: "mobile-safari",
      use: { ...devices["iPhone 13"] },
      dependencies: ["setup"],
    },
  ],

  // Web server — spin up the frontend if not already running
  // Comment this out if you run the frontend manually before E2E tests.
  // webServer: {
  //   command: "npm run dev",
  //   url: BASE_URL,
  //   reuseExistingServer: !process.env.CI,
  //   cwd: "../frontend",
  //   timeout: 120_000,
  // },
});
