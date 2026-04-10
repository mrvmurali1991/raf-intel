import { test } from '@playwright/test';

const pages = [
  ['/', 'dashboard'],
  ['/patients', 'patients'],
  ['/suspects', 'suspects'],
  ['/recapture', 'recapture'],
  ['/prospective', 'prospective'],
  ['/analysis', 'analysis'],
  ['/batch', 'batch'],
  ['/documents', 'documents'],
  ['/claims', 'claims'],
  ['/integrations', 'integrations'],
  ['/reports', 'reports'],
  ['/providers', 'providers'],
  ['/quality', 'quality'],
  ['/submissions', 'submissions'],
  ['/roi', 'roi'],
  ['/audit', 'audit'],
  ['/users', 'users'],
  ['/developer', 'developer'],
  ['/settings', 'settings'],
];

test('Screenshot all pages', async ({ page }) => {
  // Login
  await page.goto('http://localhost:3000/login', { waitUntil: 'networkidle', timeout: 30000 });
  await page.screenshot({ path: '/tmp/raf_screens/00_login.png', fullPage: true });
  await page.locator('input[type="email"]').first().fill('admin@raf.health');
  await page.locator('input[type="password"]').first().fill('admin123');
  await page.locator('button[type="submit"]').first().click();
  await page.waitForURL(url => !url.toString().includes('/login'), { timeout: 10000 });
  await page.waitForTimeout(3000);
  console.log('✅ Logged in:', page.url());

  // Visit each page
  for (let i = 0; i < pages.length; i++) {
    const [path, name] = pages[i];
    const num = String(i + 1).padStart(2, '0');
    try {
      await page.goto(`http://localhost:3000${path}`, { waitUntil: 'domcontentloaded', timeout: 30000 });
      await page.waitForTimeout(3000);
      if (page.url().includes('/login')) {
        console.log(`🔒 ${name}`);
      } else {
        await page.screenshot({ path: `/tmp/raf_screens/${num}_${name}.png`, fullPage: true });
        console.log(`✅ ${name}`);
      }
    } catch (e) {
      console.log(`❌ ${name}: ${(e as Error).message.substring(0, 60)}`);
    }
  }
});
