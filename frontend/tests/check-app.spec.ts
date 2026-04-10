import { test, expect } from '@playwright/test';

test('Check login page renders correctly', async ({ page }) => {
  // Go to login page
  await page.goto('http://localhost:3000/login', { waitUntil: 'networkidle', timeout: 30000 });

  // Screenshot the page
  await page.screenshot({ path: '/tmp/raf_login_page.png', fullPage: true });

  // Collect console errors
  const errors: string[] = [];
  page.on('console', msg => {
    if (msg.type() === 'error') {
      errors.push(msg.text());
    }
  });

  // Wait a bit for any JS to execute
  await page.waitForTimeout(3000);

  // Get page title and content
  const title = await page.title();
  const bodyText = await page.innerText('body');
  const url = page.url();

  console.log('=== PAGE INFO ===');
  console.log('URL:', url);
  console.log('Title:', title);
  console.log('Body text (first 500 chars):', bodyText.substring(0, 500));
  console.log('Console errors:', errors.length ? errors.join('\n') : 'None');

  // Take another screenshot after JS loads
  await page.screenshot({ path: '/tmp/raf_login_after.png', fullPage: true });

  // Check for common issues
  const html = await page.content();
  if (html.includes('Loading')) console.log('STATUS: Page is stuck on loading spinner');
  if (html.includes('error') || html.includes('Error')) console.log('STATUS: Page has error text');
  if (bodyText.trim().length < 10) console.log('STATUS: Page appears blank');
});
