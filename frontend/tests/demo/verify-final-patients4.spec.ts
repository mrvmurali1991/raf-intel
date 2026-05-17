import { test } from '@playwright/test';

async function login(page: any) {
  await page.goto('http://localhost:3444/login', { waitUntil: 'networkidle' });
  await page.waitForTimeout(500);
  const emailInput = await page.$('input[type="email"], input[name="email"], input[placeholder*="email" i]');
  const passwordInput = await page.$('input[type="password"]');
  if (emailInput) await emailInput.fill('admin@raf.health');
  if (passwordInput) await passwordInput.fill('Admin@123');
  const btn = await page.$('button[type="submit"]');
  if (btn) await btn.click();
  await page.waitForTimeout(4000);
}

test('full-audit-1920', async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  await login(page);
  await page.goto('http://localhost:3444/patients', { waitUntil: 'networkidle' });
  await page.waitForTimeout(3000);
  await page.screenshot({ path: '/tmp/final-1920.png', fullPage: false });

  const audit = await page.evaluate(() => {
    const allText = document.body.innerText;
    
    // Extract all patient cards: divs with specific height ranges
    const allDivs = Array.from(document.querySelectorAll('div'));
    const cardDivs = allDivs.filter(div => {
      const rect = div.getBoundingClientRect();
      const cls = div.className?.toString() || '';
      return rect.height >= 55 && rect.height <= 100 && rect.width > 600 && rect.top > 200 && rect.top < 1080
        && (cls.includes('flex') || cls.includes('border') || cls.includes('bg-'));
    });

    // Count above-fold items
    const aboveFold = cardDivs.filter(el => el.getBoundingClientRect().bottom <= 1080);

    // KPI cards: divs with "NEED REVIEW" or "UNSCORED" or number content
    const kpiPattern = /NEED REVIEW|UNSCORED|AVERAGE RAF|HCC/i;
    const kpiCards = allDivs.filter(div => {
      const text = div.innerText || '';
      return kpiPattern.test(text) && text.length < 100 && div.children.length <= 5;
    }).map(div => (div.innerText || '').trim().replace(/\n+/g, ' | ').slice(0, 80));

    // Risk factor data
    const rfPattern = /D·[\d.]+\s*\/\s*Di·[\d.]+\s*\/\s*In·[\d.]+/g;
    const rfMatches = allText.match(rfPattern) || [];

    // Row heights from the card-like divs
    const heights = cardDivs.slice(0, 15).map(d => Math.round(d.getBoundingClientRect().height));

    // Check for red/pink row backgrounds
    const coloredRows = cardDivs.filter(div => {
      const style = window.getComputedStyle(div);
      const bg = style.backgroundColor;
      return bg.includes('255') && (bg.includes('220') || bg.includes('200') || bg.includes('239'));
    }).map(div => ({ bg: window.getComputedStyle(div).backgroundColor, top: Math.round(div.getBoundingClientRect().top) }));

    // Check filter pills
    const filterPills = allDivs.filter(div => {
      const text = div.innerText?.trim() || '';
      return /^(High Risk|Medium|Low|Unscored|All Patients)/.test(text) && text.length < 40;
    }).map(div => ({
      text: div.innerText.trim().slice(0, 30),
      bg: window.getComputedStyle(div).backgroundColor,
    }));

    // Check for Import button
    const importBtn = Array.from(document.querySelectorAll('button')).find(b => b.innerText.toLowerCase().includes('import'));
    const exportBtn = Array.from(document.querySelectorAll('button')).find(b => b.innerText.toLowerCase().includes('export'));

    // Check overflow
    const hasOverflow = document.documentElement.scrollWidth > document.documentElement.clientWidth;

    // Full patient list text
    const patientList = allText.slice(allText.indexOf('Worklist'), allText.indexOf('Worklist') + 2000);

    return {
      cardCount: cardDivs.length,
      aboveFoldCount: aboveFold.length,
      heights: heights.slice(0, 15),
      rfMatches,
      kpiCards: kpiCards.slice(0, 6),
      coloredRows: coloredRows.slice(0, 5),
      filterPills,
      hasImport: !!importBtn,
      importText: importBtn?.innerText?.trim(),
      hasExport: !!exportBtn,
      exportText: exportBtn?.innerText?.trim(),
      hasOverflow,
      patientListText: patientList.slice(0, 1500),
    };
  });

  console.log(JSON.stringify(audit, null, 2));
});
