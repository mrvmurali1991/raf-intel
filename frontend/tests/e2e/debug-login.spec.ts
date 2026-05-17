import { test } from '@playwright/test';
test('debug login', async ({ page }) => {
  const reqs: string[] = [];
  page.on('request', r => { if (r.url().includes('8500') || r.url().includes('login')) reqs.push(r.method() + ' ' + r.url()); });
  page.on('requestfailed', r => reqs.push('FAILED: ' + r.url() + ' ' + r.failure()?.errorText));
  page.on('response', async r => { if (r.url().includes('login')) reqs.push('RESP ' + r.status() + ' ' + r.url()); });
  await page.goto('http://localhost:3444/login');
  await page.waitForLoadState('networkidle').catch(()=>{});
  await page.locator('input[type=email]').first().fill('admin@raf.health');
  await page.locator('input[type=password]').first().fill('Admin@123');
  await page.locator('button:has-text("Secure Sign In")').click();
  await page.waitForTimeout(3000);
  console.log('REQUESTS:', JSON.stringify(reqs, null, 2));
});
