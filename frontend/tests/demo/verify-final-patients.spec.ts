import { test, expect, Page } from '@playwright/test';

const viewports = [
  { w: 1920, h: 1080 },
  { w: 1440, h: 900 },
  { w: 1280, h: 800 },
  { w: 1024, h: 768 },
  { w: 414, h: 896 },
];

async function loginAndGoto(page: Page, w: number, h: number) {
  await page.setViewportSize({ width: w, height: h });
  await page.goto('http://localhost:3444/login', { waitUntil: 'domcontentloaded' });
  await page.fill('input[type="email"]', 'admin@raf.health');
  await page.fill('input[type="password"]', 'Admin@123');
  await page.click('button[type="submit"]');
  await page.waitForTimeout(3000);
  await page.goto('http://localhost:3444/patients', { waitUntil: 'networkidle' });
  await page.waitForTimeout(2500);
}

for (const vp of viewports) {
  test(`verify-${vp.w}x${vp.h}`, async ({ page }) => {
    await loginAndGoto(page, vp.w, vp.h);
    await page.screenshot({ path: `/tmp/final-${vp.w}.png`, fullPage: false });

    const metrics = await page.evaluate(() => {
      const allTr = Array.from(document.querySelectorAll('tr'));
      const dataRows = allTr.filter(r => r.querySelectorAll('td').length > 2);
      const visibleRows = dataRows.filter(r => {
        const rect = r.getBoundingClientRect();
        return rect.top >= 0 && rect.bottom <= window.innerHeight && rect.height > 10;
      });
      const heights = dataRows.slice(0, 12).map(r => Math.round(r.getBoundingClientRect().height));

      const h1 = document.querySelector('h1');
      const allText = document.body.innerText;

      // Risk factors: look for cells with · character
      const tds = Array.from(document.querySelectorAll('td'));
      const rfSamples = tds.filter(td => td.textContent && td.textContent.includes('·')).slice(0, 3).map(td => td.textContent!.trim().slice(0, 60));
      const dashOnlyCells = tds.filter(td => td.textContent && td.textContent.trim() === '—').length;

      // Amber alert
      const allElements = Array.from(document.querySelectorAll('*'));
      const amberEls = allElements.filter(el => {
        const style = window.getComputedStyle(el);
        const bg = style.backgroundColor;
        const text = el.textContent || '';
        return (bg.includes('255, 165') || bg.includes('255, 193') || bg.includes('245, 158') || 
                el.className.toString().includes('amber') || el.className.toString().includes('warning') || el.className.toString().includes('yellow')) &&
               el.children.length === 0 && text.trim().length > 10 && text.trim().length < 200;
      });

      // Buttons
      const btns = Array.from(document.querySelectorAll('button, [role="button"]')).map(b => (b as HTMLElement).innerText.trim()).filter(t => t.length > 0);

      // KPI cards - look for stat cards
      const statCards = Array.from(document.querySelectorAll('[class*="card"], [class*="stat"], [class*="kpi"]'));
      
      // Overflow
      const hasOverflow = document.documentElement.scrollWidth > document.documentElement.clientWidth;

      // Row background colors for high-risk
      const rowBgs = dataRows.slice(0, 5).map(r => {
        const style = window.getComputedStyle(r);
        return style.backgroundColor;
      });

      return {
        visibleRowCount: visibleRows.length,
        rowHeights: heights,
        h1Text: h1 ? h1.textContent!.trim() : 'NOT FOUND',
        rfSamples,
        dashOnlyCells,
        amberWarnings: amberEls.slice(0, 3).map(e => e.textContent!.trim().slice(0, 60)),
        buttons: btns.slice(0, 15),
        hasOverflow,
        rowBgs,
        bodyTextSnippet: allText.slice(0, 300),
      };
    });

    console.log(`\n=== ${vp.w}x${vp.h} ===`);
    console.log(JSON.stringify(metrics, null, 2));
  });
}
