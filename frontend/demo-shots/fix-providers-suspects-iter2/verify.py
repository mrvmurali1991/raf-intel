"""Playwright verification script for iter-2 fixes."""
import asyncio
from playwright.async_api import async_playwright

BASE = "http://localhost:3444"
OUT = "/Users/murali/Desktop/raf-intelligence/frontend/demo-shots/fix-providers-suspects-iter2"


async def login(page):
    await page.goto(f"{BASE}/login", wait_until="domcontentloaded")
    await page.wait_for_timeout(2000)
    await page.fill('input[type="email"]', "admin@raf.health")
    await page.fill('input[type="password"]', "Admin@123")
    await page.click('button[type="submit"]')
    await page.wait_for_url(lambda url: "/login" not in url, timeout=15000)
    await page.wait_for_timeout(2000)


async def verify_providers_mobile(page):
    await page.set_viewport_size({"width": 414, "height": 896})
    await page.goto(f"{BASE}/providers", wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)
    await page.screenshot(path=f"{OUT}/providers-mobile-initial.png", full_page=False)

    # Find first expand button and click it
    expand_btn = page.locator("button:has-text('Scorecard')").first
    await expand_btn.wait_for(state="visible", timeout=10000)
    await expand_btn.click()
    await page.wait_for_timeout(1500)
    await page.screenshot(path=f"{OUT}/providers-mobile-expanded.png", full_page=False)
    print("[OK] providers mobile drilldown screenshot taken")


async def verify_suspects_chips(page):
    await page.set_viewport_size({"width": 1440, "height": 900})
    await page.goto(f"{BASE}/suspects", wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)
    await page.screenshot(path=f"{OUT}/suspects-initial.png", full_page=False)

    # Click each chip in sequence
    chip_labels = ["Open", "Accepted", "Dismissed", "All"]
    for label in chip_labels:
        chip = page.locator(f"button:has-text('{label}')").first
        await chip.wait_for(state="visible", timeout=5000)
        await chip.click()
        await page.wait_for_timeout(300)

        dialog_count = await page.locator('[role="dialog"]').count()
        print(f"After clicking '{label}': dialog count = {dialog_count}")
        assert dialog_count == 0, f"Command palette appeared after clicking '{label}' chip!"

    await page.screenshot(path=f"{OUT}/suspects-chips-no-palette.png", full_page=False)
    print("[OK] suspects chips: no dialog appeared")


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        await login(page)
        await verify_providers_mobile(page)
        await verify_suspects_chips(page)

        await browser.close()
        print("[DONE] All verifications passed.")


asyncio.run(main())
