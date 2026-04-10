import { test } from '@playwright/test';
test('Check what browser shows', async ({ page }) => {
  page.on('pageerror', err => console.log('PAGE ERROR:', err.message.substring(0, 200)));
  page.on('console', msg => {
    if (msg.type() === 'error') console.log('CONSOLE ERROR:', msg.text().substring(0, 200));
  });
  
  await page.goto('http://localhost:3000/login', { waitUntil: 'domcontentloaded', timeout: 15000 });
  await page.waitForTimeout(5000);
  
  const bodyText = await page.innerText('body').catch(() => 'EMPTY');
  console.log('BODY:', bodyText.substring(0, 300));
  console.log('URL:', page.url());
  await page.screenshot({ path: '/tmp/raf_check.png', fullPage: true });
});
