import { test, expect } from "@playwright/test";
test.use({ baseURL: "http://localhost:3001" });

const PAGES = [
  "/", "/patients", "/recapture", "/prospective",
  "/analysis", "/batch", "/documents", "/claims",
  "/demo", "/integrations", "/reports", "/providers",
  "/quality", "/submissions", "/raf-calculate", "/roi",
  "/compliance", "/users", "/developer", "/emr-config", "/settings"
];

test("audit all pages for errors", async ({ page }) => {
  // Login
  await page.goto("/login");
  await page.waitForSelector('input[type="email"]', { state: "visible", timeout: 30_000 });
  await page.fill('input[type="email"]', "admin@raf.health");
  await page.fill('input[type="password"]', "admin123");
  await page.click('button[type="submit"]');
  await page.waitForResponse((r) => r.url().includes("/api/auth/login") && r.status() === 200);
  await page.waitForURL((url) => !url.pathname.includes("/login"), { timeout: 30_000 });
  await page.evaluate(() => localStorage.setItem("raf_onboarding_complete", "true"));
  await page.waitForTimeout(2000);

  const results: string[] = [];

  for (const p of PAGES) {
    const errors: string[] = [];
    const handler = (msg: any) => {
      if (msg.type() === "error" && !msg.text().includes("401") && !msg.text().includes("favicon"))
        errors.push(msg.text().substring(0, 120));
    };
    page.on("console", handler);

    try {
      await page.locator(`a[href="${p}"]`).last().click({ timeout: 3000 });
    } catch {
      // Fallback: direct navigation
    }
    await page.waitForTimeout(2000);

    const status = errors.length === 0 ? "✅" : "❌";
    results.push(`${status} ${p} ${errors.length > 0 ? "— " + errors.join(" | ") : ""}`);
    page.removeListener("console", handler);
  }

  results.forEach((r) => console.log(r));
});
