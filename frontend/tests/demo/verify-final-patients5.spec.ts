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

test('row-height-measure', async ({ page }) => {
  await login(page, 1920, 1080);
  
  const heights = await page.evaluate(() => {
    // The table is NOT using <tr> - it's divs. Find grid/flex rows.
    // Looking for elements that are direct siblings and have similar heights
    const allDivs = Array.from(document.querySelectorAll('div'));
    
    // Look for divs containing "Johnson" or "Davis" (first patient names)
    const patientDivs = allDivs.filter(div => {
      const text = div.innerText || '';
      return (text.includes('Johnson') || text.includes('Davis') || text.includes('Thompson')) && 
             !text.includes('Worklist') && text.length < 300;
    });
    
    return patientDivs.slice(0, 5).map(div => {
      const rect = div.getBoundingClientRect();
      const style = window.getComputedStyle(div);
      return {
        text: div.innerText?.trim().slice(0, 60),
        height: Math.round(rect.height),
        top: Math.round(rect.top),
        className: div.className?.toString().slice(0, 100),
        bg: style.backgroundColor,
      };
    });
  });
  
  console.log('Patient row measurements:');
  console.log(JSON.stringify(heights, null, 2));
  
  // Also check parent container
  const containerInfo = await page.evaluate(() => {
    const allDivs = Array.from(document.querySelectorAll('div'));
    const johnsDiv = allDivs.find(d => d.innerText?.includes('Johnson, James') && d.innerText?.length < 200);
    if (!johnsDiv) return { error: 'not found' };
    const parent = johnsDiv.parentElement;
    const grandparent = parent?.parentElement;
    
    return {
      selfHeight: Math.round(johnsDiv.getBoundingClientRect().height),
      selfClass: johnsDiv.className?.toString().slice(0, 120),
      selfBg: window.getComputedStyle(johnsDiv).backgroundColor,
      selfTop: Math.round(johnsDiv.getBoundingClientRect().top),
      parentHeight: parent ? Math.round(parent.getBoundingClientRect().height) : 0,
      parentClass: parent?.className?.toString().slice(0, 120),
      gpHeight: grandparent ? Math.round(grandparent.getBoundingClientRect().height) : 0,
      gpClass: grandparent?.className?.toString().slice(0, 120),
    };
  });
  
  console.log('\nContainer info:');
  console.log(JSON.stringify(containerInfo, null, 2));
  
  // Count visible rows
  const rowCount = await page.evaluate(() => {
    const allDivs = Array.from(document.querySelectorAll('div'));
    // Find the "row" pattern: repeated divs with same class in the list area
    const johnsDiv = allDivs.find(d => d.innerText?.includes('Johnson, James') && d.innerText?.length < 200);
    if (!johnsDiv) return { error: 'no johnson div' };
    
    const parent = johnsDiv.parentElement;
    if (!parent) return { error: 'no parent' };
    
    const siblings = Array.from(parent.children);
    const visibleSiblings = siblings.filter(s => {
      const rect = (s as HTMLElement).getBoundingClientRect();
      return rect.top >= 0 && rect.bottom <= 1080 && rect.height > 20;
    });
    
    return {
      totalChildren: siblings.length,
      visibleCount: visibleSiblings.length,
      childHeights: siblings.slice(0, 15).map(s => Math.round((s as HTMLElement).getBoundingClientRect().height)),
      parentClass: parent.className?.toString().slice(0, 100),
    };
  });
  
  console.log('\nRow count:');
  console.log(JSON.stringify(rowCount, null, 2));
});
