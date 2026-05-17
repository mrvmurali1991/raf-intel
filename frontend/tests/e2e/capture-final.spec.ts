import { test, expect } from '@playwright/test';

test.use({ viewport: { width: 1440, height: 900 } });
const BASE = 'http://localhost:3444';
const SHOTS = '/tmp/raf-demo';

test('demo: login + dashboards', async ({ page }) => {
  // Login page
  await page.goto(BASE + '/login');
  await page.waitForLoadState('networkidle').catch(() => {});
  await expect(page).toHaveTitle(/Sign in|Login|RAF Intelligence/i, { timeout: 8000 }).catch(() => {});
  await page.screenshot({ path: SHOTS + '/01-login.png', fullPage: false });

  // Trigger field validation (onBlur via Tab keypress so blur DOM event fires)
  const emailInput = page.locator('input[type=email]').first();
  await emailInput.click();
  await emailInput.fill('not-an-email');
  await page.keyboard.press('Tab');
  await page.waitForTimeout(600);
  await page.screenshot({ path: SHOTS + '/02-login-onblur-error.png', fullPage: false });

  // Real login
  await page.fill('input[type=email], input[name=email]', 'admin@raf.health');
  await page.fill('input[type=password], input[name=password]', 'Admin@123');
  await page.locator('button[type=submit], button:has-text("Sign in")').first().click();
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(5000);
  await page.screenshot({ path: SHOTS + '/03-home-after-login.png', fullPage: true });

  // Patients page
  await page.goto(BASE + '/patients');
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(5000);
  await page.screenshot({ path: SHOTS + '/04-patients.png', fullPage: true });

  // Review queue (the page with new urgency-tier row colors)
  await page.goto(BASE + '/review-queue');
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(5000);
  await page.screenshot({ path: SHOTS + '/05-review-queue.png', fullPage: true });

  // Recapture (new bento layout)
  await page.goto(BASE + '/recapture');
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(5000);
  await page.screenshot({ path: SHOTS + '/06-recapture-bento.png', fullPage: true });

  // Tablet view
  await page.setViewportSize({ width: 1024, height: 1366 });
  await page.goto(BASE + '/patients');
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(5000);
  await page.screenshot({ path: SHOTS + '/07-patients-tablet.png', fullPage: true });
});
