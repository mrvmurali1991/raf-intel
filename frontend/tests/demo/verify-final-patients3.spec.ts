import { test } from '@playwright/test';

async function doLogin(page: any, w: number, h: number) {
  await page.setViewportSize({ width: w, height: h });
  // Go directly to the app login (not the marketing page)
  await page.goto('http://localhost:3444/login', { waitUntil: 'networkidle' });
  await page.waitForTimeout(1000);
  
  // Check what's on the page
  const pageContent = await page.evaluate(() => document.body.innerText.slice(0, 200));
  console.log(`Page at /login (${w}x${h}):`, pageContent.slice(0, 100));
  
  // Find email/password inputs
  const emailInput = await page.$('input[type="email"], input[name="email"], input[placeholder*="email" i], input[placeholder*="Email" i]');
  const passwordInput = await page.$('input[type="password"]');
  
  if (emailInput) {
    await emailInput.fill('admin@raf.health');
  }
  if (passwordInput) {
    await passwordInput.fill('Admin@123');
  }
  
  const submitBtn = await page.$('button[type="submit"], button:has-text("Sign In"), button:has-text("Login"), button:has-text("Secure Sign In")');
  if (submitBtn) {
    await submitBtn.click();
  }
  
  await page.waitForTimeout(4000);
  
  const afterUrl = page.url();
  console.log('After login URL:', afterUrl);
  
  // Navigate to patients
  await page.goto('http://localhost:3444/patients', { waitUntil: 'networkidle' });
  await page.waitForTimeout(3000);
  
  const finalUrl = page.url();
  console.log('Patients URL:', finalUrl);
  return finalUrl;
}

test('verify-all-viewports', async ({ page }) => {
  const viewports = [
    { w: 1920, h: 1080 },
    { w: 1440, h: 900 },
    { w: 1280, h: 800 },
    { w: 1024, h: 768 },
    { w: 414, h: 896 },
  ];

  for (const vp of viewports) {
    const url = await doLogin(page, vp.w, vp.h);
    
    await page.screenshot({ path: `/tmp/final-${vp.w}.png`, fullPage: false });
    
    const metrics = await page.evaluate(() => {
      // All divs that look like patient card rows
      const rowDivs = Array.from(document.querySelectorAll('div[class*="bg-white"], div[class*="bg-slate"], div[class*="border-b"]'))
        .filter(el => {
          const rect = el.getBoundingClientRect();
          return rect.height >= 50 && rect.height <= 120 && rect.width > 500 && rect.top > 150 && rect.top < window.innerHeight;
        });
      
      // h1
      const h1 = document.querySelector('h1');
      
      // all text with dots (·) for risk factors
      const allText = document.body.innerText;
      const dotMatches = allText.match(/[DI][a-z]*·[\d.]+/g) || [];
      
      // buttons
      const btns = Array.from(document.querySelectorAll('button')).map(b => (b as HTMLElement).innerText.trim()).filter(Boolean);
      
      // overflow
      const hasOverflow = document.documentElement.scrollWidth > document.documentElement.clientWidth;
      
      // Full page text for analysis
      const pageText = allText.slice(0, 1000);
      
      return {
        visibleCardRows: rowDivs.length,
        rowHeights: rowDivs.slice(0, 12).map(el => Math.round(el.getBoundingClientRect().height)),
        h1Text: h1?.textContent?.trim() || 'NOT FOUND',
        dotMatches: dotMatches.slice(0, 5),
        buttons: btns.slice(0, 20),
        hasOverflow,
        pageText,
      };
    });
    
    console.log(`\n=== ${vp.w}x${vp.h} (${url}) ===`);
    console.log(JSON.stringify(metrics, null, 2));
  }
});
