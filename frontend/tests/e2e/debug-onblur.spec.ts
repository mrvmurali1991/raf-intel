import { test } from '@playwright/test';
test('debug onblur', async ({ page }) => {
  await page.goto('http://localhost:3444/login');
  await page.waitForLoadState('networkidle').catch(() => {});
  const email = page.locator('input[type=email]').first();
  await email.click();
  await email.fill('not-an-email');
  await page.keyboard.press('Tab');
  await page.waitForTimeout(800);
  const debug = await page.evaluate(() => {
    const inp = document.querySelector('input[type=email]') as HTMLInputElement;
    const err = document.querySelector('#email-error');
    return {
      inputValue: inp?.value,
      ariaInvalid: inp?.getAttribute('aria-invalid'),
      ariaDescribedBy: inp?.getAttribute('aria-describedby'),
      errorElExists: !!err,
      errorText: err?.textContent,
    };
  });
  console.log('DEBUG:', JSON.stringify(debug));
  // Crop screenshot to form area
  const form = page.locator('form, .Welcome, [class*="card"]').first();
  await form.screenshot({ path: '/tmp/raf-demo/debug-form.png' });
});
