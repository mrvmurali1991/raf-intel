import { test } from '@playwright/test';

const viewports = [
  { name: '1920', width: 1920, height: 1080 },
  { name: '1440', width: 1440, height: 900 },
  { name: '1280', width: 1280, height: 800 },
  { name: '1024', width: 1024, height: 768 },
  { name: '414', width: 414, height: 896 },
];

for (const vp of viewports) {
  test(`patients ${vp.name}`, async ({ page }) => {
    await page.setViewportSize({ width: vp.width, height: vp.height });
    await page.goto('http://localhost:3444/login');
    await page.waitForLoadState('domcontentloaded');
    // Use placeholder/label probing
    const emailInput = page.locator('input').filter({ hasNot: page.locator('[type=password]') }).first();
    await emailInput.fill('admin@raf.health');
    await page.locator('input[type=password]').fill('Admin@123');
    await page.locator('button[type=submit]').click();
    // wait for navigation away from /login
    await page.waitForURL((url) => !url.pathname.endsWith('/login'), { timeout: 20000 });
    await page.goto('http://localhost:3444/patients');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2500);
    await page.screenshot({ path: `/tmp/final-verify-${vp.name}.png`, fullPage: false });
    console.log(`[${vp.name}] final url:`, page.url());
  });
}
