import { test } from '@playwright/test';

test('deep-dom-1920', async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.goto('http://localhost:3444/login', { waitUntil: 'domcontentloaded' });
  await page.fill('input[type="email"]', 'admin@raf.health');
  await page.fill('input[type="password"]', 'Admin@123');
  await page.click('button[type="submit"]');
  await page.waitForTimeout(3000);
  await page.goto('http://localhost:3444/patients', { waitUntil: 'networkidle' });
  await page.waitForTimeout(3000);

  const info = await page.evaluate(() => {
    // Try all possible row selectors
    const selectors = ['tbody tr', 'tr', '[role="row"]', '[data-row]', 'li[class*="row"]', 'div[class*="row"]'];
    const results: Record<string, number> = {};
    for (const sel of selectors) {
      results[sel] = document.querySelectorAll(sel).length;
    }

    // Get all elements with height between 50-100px that are inside main content
    const main = document.querySelector('main') || document.body;
    const allEls = Array.from(main.querySelectorAll('*'));
    const rowLike = allEls.filter(el => {
      const rect = el.getBoundingClientRect();
      return rect.height >= 50 && rect.height <= 100 && rect.width > 500 && rect.top > 100 && rect.top < 1080;
    });

    // Sample visible text in table area
    const tableEl = document.querySelector('table');
    const tableText = tableEl ? tableEl.innerText?.slice(0, 500) : 'NO TABLE ELEMENT';

    // Get the actual DOM structure near the patient list
    const listContainer = document.querySelector('[class*="patient"]') || 
                          document.querySelector('[class*="worklist"]') ||
                          document.querySelector('table') ||
                          document.querySelector('[role="grid"]');

    return {
      selectorCounts: results,
      rowLikeSample: rowLike.slice(0, 3).map(el => ({
        tag: el.tagName,
        cls: el.className?.toString().slice(0, 80),
        height: Math.round(el.getBoundingClientRect().height),
        top: Math.round(el.getBoundingClientRect().top),
      })),
      tableText,
      listContainerTag: listContainer ? listContainer.tagName : 'NONE',
      listContainerClass: listContainer ? listContainer.className?.toString().slice(0, 100) : '',
      listContainerInner: listContainer ? listContainer.innerHTML?.slice(0, 400) : '',
    };
  });

  console.log(JSON.stringify(info, null, 2));
  await page.screenshot({ path: '/tmp/final-1920.png', fullPage: false });
});
