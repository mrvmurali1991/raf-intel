import { test } from '@playwright/test';

const viewports = [
  { name: '1920', width: 1920, height: 1080 },
  { name: '1440', width: 1440, height: 900 },
  { name: '1280', width: 1280, height: 800 },
  { name: '414', width: 414, height: 896 },
];

for (const vp of viewports) {
  test(`detail ${vp.name}`, async ({ page }) => {
    await page.setViewportSize({ width: vp.width, height: vp.height });
    await page.goto('http://localhost:3444/login');
    await page.waitForLoadState('domcontentloaded');
    const emailInput = page.locator('input').filter({ hasNot: page.locator('[type=password]') }).first();
    await emailInput.fill('admin@raf.health');
    await page.locator('input[type=password]').fill('Admin@123');
    await page.locator('button[type=submit]').click();
    await page.waitForURL((url) => !url.pathname.endsWith('/login'), { timeout: 20000 });
    await page.goto('http://localhost:3444/patients/6');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2500);
    await page.screenshot({ path: `/tmp/detail-verify-${vp.name}.png`, fullPage: false });
  });
}
