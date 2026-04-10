import { test } from '@playwright/test';
test('Final error check - all pages', async ({ page }) => {
  const errors: Record<string, string[]> = {};
  page.on('console', msg => {
    if (msg.type() === 'error') {
      const p = page.url().replace('http://localhost:3000', '') || '/';
      if (!errors[p]) errors[p] = [];
      const t = msg.text().substring(0, 150);
      if (!t.includes('favicon') && !t.includes('react-devtools') && !t.includes('%o'))
        errors[p].push(t);
    }
  });

  await page.goto('http://localhost:3000/login', { waitUntil: 'networkidle', timeout: 30000 });
  await page.locator('input[type="email"]').first().fill('admin@raf.health');
  await page.locator('input[type="password"]').first().fill('admin123');
  await page.locator('button[type="submit"]').first().click();
  await page.waitForURL(u => !u.toString().includes('/login'), { timeout: 10000 });
  await page.waitForTimeout(2000);

  const pages = ['/', '/patients', '/suspects', '/recapture', '/prospective', '/analysis',
    '/batch', '/documents', '/claims', '/integrations', '/reports', '/providers',
    '/quality', '/submissions', '/roi', '/audit', '/users', '/developer', '/settings'];

  for (const p of pages) {
    await page.goto(`http://localhost:3000${p}`, { waitUntil: 'domcontentloaded', timeout: 20000 });
    await page.waitForTimeout(2000);
  }

  let total = 0;
  for (const [url, errs] of Object.entries(errors)) {
    const unique = [...new Set(errs)];
    if (unique.length > 0) {
      console.log(`${url}: ${unique.length} error(s)`);
      for (const e of unique) console.log(`  - ${e}`);
      total += unique.length;
    }
  }
  if (total === 0) console.log('✅ ZERO ERRORS across all 19 pages!');
  else console.log(`\n❌ ${total} errors remaining`);
});
