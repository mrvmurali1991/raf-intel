import { test } from '@playwright/test';

async function login(page: any, w: number, h: number) {
  await page.setViewportSize({ width: w, height: h });
  await page.goto('http://localhost:3444/login', { waitUntil: 'networkidle' });
  await page.waitForTimeout(500);
  const emailInput = await page.$('input[type="email"], input[name="email"]');
  const passwordInput = await page.$('input[type="password"]');
  if (emailInput) await emailInput.fill('admin@raf.health');
  if (passwordInput) await passwordInput.fill('Admin@123');
  const btn = await page.$('button[type="submit"]');
  if (btn) await btn.click();
  await page.waitForTimeout(4000);
  await page.goto('http://localhost:3444/patients', { waitUntil: 'networkidle' });
  await page.waitForTimeout(3000);
}

const VIEWPORTS = [
  { w: 1920, h: 1080 },
  { w: 1440, h: 900 },
  { w: 1280, h: 800 },
  { w: 1024, h: 768 },
  { w: 414, h: 896 },
];

for (const vp of VIEWPORTS) {
  test(`screenshot-${vp.w}x${vp.h}`, async ({ page }) => {
    await login(page, vp.w, vp.h);
    await page.screenshot({ path: `/tmp/final-${vp.w}.png`, fullPage: false });
    
    const data = await page.evaluate((vpHeight) => {
      const allDivs = Array.from(document.querySelectorAll('div'));
      
      // Find all worklist-grid rows
      const wlRows = allDivs.filter(d => d.className?.toString() === 'worklist-grid');
      const visibleRows = wlRows.filter(d => {
        const rect = d.getBoundingClientRect();
        return rect.top >= 0 && rect.bottom <= vpHeight;
      });
      
      // Full page text
      const allText = document.body.innerText;
      const worklistIdx = allText.indexOf('Worklist');
      const pageSection = worklistIdx >= 0 ? allText.slice(worklistIdx, worklistIdx + 3000) : allText.slice(0, 3000);
      
      // KPI order check
      const needReviewIdx = allText.indexOf('NEED REVIEW');
      const unscoredIdx = allText.indexOf('UNSCORED');
      const avgRafIdx = allText.indexOf('AVERAGE RAF');
      const hccsIdx = allText.indexOf('HCCS CAPTURED');
      
      // Filter pills
      const filterBtns = Array.from(document.querySelectorAll('button')).filter(b => {
        const t = b.innerText?.trim() || '';
        return /High Risk|Medium|Low|Unscored/.test(t) && t.length < 30;
      }).map(b => {
        const style = window.getComputedStyle(b);
        return { text: b.innerText.trim(), bg: style.backgroundColor, color: style.color };
      });
      
      // Import/Export
      const importBtn = Array.from(document.querySelectorAll('button')).find(b => /import/i.test(b.innerText));
      const exportBtn = Array.from(document.querySelectorAll('button')).find(b => /export/i.test(b.innerText));
      
      // Overflow
      const hasOverflow = document.documentElement.scrollWidth > document.documentElement.clientWidth;
      
      // Amber/warning banner  
      const amberBanner = allDivs.filter(d => {
        const text = d.innerText?.trim() || '';
        const style = window.getComputedStyle(d);
        const bg = style.backgroundColor;
        const rect = d.getBoundingClientRect();
        return rect.top > 0 && rect.top < 200 && rect.height > 20 && rect.width > 400 &&
          (bg.includes('245, 158') || bg.includes('253, 224') || bg.includes('254, 243') || 
           d.className?.toString().includes('amber') || d.className?.toString().includes('warning')) &&
          text.length > 5;
      }).map(d => d.innerText?.trim().slice(0, 80));
      
      return {
        totalWlRows: wlRows.length,
        visibleRowCount: visibleRows.length,
        rowHeights: wlRows.map(d => Math.round(d.getBoundingClientRect().height)),
        rowTops: wlRows.map(d => Math.round(d.getBoundingClientRect().top)),
        rowBgs: wlRows.map(d => window.getComputedStyle(d).backgroundColor),
        kpiOrder: { needReviewIdx, unscoredIdx, avgRafIdx, hccsIdx },
        filterPills: filterBtns,
        hasImport: !!importBtn,
        hasExport: !!exportBtn,
        hasOverflow,
        amberBanner,
        pageSection,
      };
    }, vp.h);
    
    console.log(`\n=== ${vp.w}x${vp.h} ===`);
    console.log(JSON.stringify({
      ...data,
      pageSection: data.pageSection.slice(0, 600),
    }, null, 2));
  });
}
