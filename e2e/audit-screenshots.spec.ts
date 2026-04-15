import { test, expect } from "@playwright/test";

const SCREENSHOT_DIR = "/tmp/screenshots";

const pages = [
  { name: "04-raf-scores", path: "/raf-dashboard" },
  { name: "05-data-quality", path: "/data-quality" },
  { name: "06-pipeline", path: "/pipeline" },
  { name: "07-suspects", path: "/suspects" },
  { name: "08-care-gaps", path: "/care-gaps" },
  { name: "09-attestations", path: "/attestations" },
  { name: "10-reports", path: "/reports" },
  { name: "11-emr-config", path: "/emr-config" },
  { name: "12-coder-worklist", path: "/coder-worklist" },
];

test.use({
  viewport: { width: 1920, height: 1080 },
  storageState: undefined,
});

test("audit screenshots of all major pages", async ({ page }) => {
  test.setTimeout(120_000);

  // Login
  await page.goto("/login");
  await page.waitForLoadState("networkidle");
  await page.fill('input[name="email"], input[type="email"]', "admin@raf.health");
  await page.fill('input[name="password"], input[type="password"]', "Admin@123");
  await page.click('button[type="submit"]');
  await page.waitForURL("**/dashboard**", { timeout: 15000 }).catch(() => {});
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(2000);

  // 01 - Dashboard
  await page.screenshot({ path: `${SCREENSHOT_DIR}/01-dashboard.png`, fullPage: true });
  console.log("✓ 01-dashboard");

  // 02 - Patients
  await page.goto("/patients");
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(2000);
  await page.screenshot({ path: `${SCREENSHOT_DIR}/02-patients.png`, fullPage: true });
  console.log("✓ 02-patients");

  // 03 - Patient detail (click first patient row)
  const firstPatientLink = page.locator("table tbody tr a, table tbody tr td").first();
  if (await firstPatientLink.isVisible({ timeout: 5000 }).catch(() => false)) {
    await firstPatientLink.click();
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(2000);
    await page.screenshot({ path: `${SCREENSHOT_DIR}/03-patient-detail.png`, fullPage: true });
    console.log("✓ 03-patient-detail");
  } else {
    console.log("⚠ 03-patient-detail SKIPPED - no patient rows found");
  }

  // Remaining pages
  for (const p of pages) {
    await page.goto(p.path);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(2000);
    const is404 = await page.locator("text=404, text=not found, text=Not Found").first().isVisible({ timeout: 2000 }).catch(() => false);
    if (is404) {
      console.log(`⚠ ${p.name} SKIPPED - 404`);
      continue;
    }
    await page.screenshot({ path: `${SCREENSHOT_DIR}/${p.name}.png`, fullPage: true });
    console.log(`✓ ${p.name}`);
  }
});
