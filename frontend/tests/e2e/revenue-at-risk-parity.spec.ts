/**
 * @smoke
 *
 * Revenue-at-Risk parity test
 *
 * Asserts that the Revenue-at-Risk / Revenue Opportunity dollar value exposed
 * on each of the four primary analytics pages is consistent — proving the
 * single-source-of-truth metrics layer is wired correctly end-to-end.
 *
 * Each page renders a wrapper element with data-testid="revenue-at-risk-value".
 * The test reads the first visible dollar figure from that wrapper, normalises
 * it to a plain integer, and asserts all four values are within $1 of each other.
 *
 * The _meta transparency proof is satisfied by asserting the info icon
 * (data-testid="revenue-at-risk-info") is present on at least one page.
 *
 * Tag: @smoke — runs in CI via `grep -r "@smoke"` filter or
 *   `npx playwright test --grep @smoke`.
 */

import { test, expect } from "@playwright/test";
import { loginAsAdmin } from "./helpers/auth";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Parse a dollar string such as "$1,234,567", "$1.2M", "$456K", "—" into an
 * integer (cents-free). Returns NaN for empty / unavailable values so the
 * caller can skip or fail gracefully.
 */
function parseDollar(raw: string): number {
  const s = raw.trim();
  if (!s || s === "—" || s === "--") return NaN;

  // Strip leading "$" and commas.
  const clean = s.replace(/\$|,/g, "").trim();

  // Handle suffixed compact values: e.g. "1.2M", "456K"
  const mMatch = clean.match(/^([\d.]+)\s*[Mm]$/);
  if (mMatch) return Math.round(parseFloat(mMatch[1]) * 1_000_000);

  const kMatch = clean.match(/^([\d.]+)\s*[Kk]$/);
  if (kMatch) return Math.round(parseFloat(kMatch[1]) * 1_000);

  const n = parseFloat(clean);
  return isNaN(n) ? NaN : Math.round(n);
}

/**
 * Navigate to `path`, wait for the revenue-at-risk wrapper to appear, then
 * return the normalised dollar integer and whether the info icon is visible.
 */
async function collectRevenue(
  page: Parameters<typeof loginAsAdmin>[0],
  path: string,
): Promise<{ dollars: number; hasInfoIcon: boolean }> {
  await page.goto(path);

  // Wait for the revenue wrapper — up to 20 s to account for API latency.
  const wrapper = page.locator('[data-testid="revenue-at-risk-value"]').first();
  await wrapper.waitFor({ state: "visible", timeout: 20_000 });

  // Extract first dollar-like text node from the wrapper subtree.
  const rawText = await wrapper.evaluate((el: Element) => {
    // Walk all text nodes and return the first one that looks like a dollar value.
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    let node: Node | null;
    while ((node = walker.nextNode())) {
      const t = (node.textContent ?? "").trim();
      if (/^\$[\d,.]+[MmKk]?$|^\$[\d,.]+$/.test(t)) return t;
    }
    // Fallback: innerText of the value span (tabular-nums).
    const span = el.querySelector(".tabular-nums, [class*='text-metric'], p[style*='font-size: 32']");
    return span ? (span as HTMLElement).innerText.trim() : el.textContent?.trim() ?? "";
  });

  const dollars = parseDollar(rawText);

  // Check for info icon on this page.
  const hasInfoIcon = await page
    .locator('[data-testid="revenue-at-risk-info"]')
    .first()
    .isVisible()
    .catch(() => false);

  return { dollars, hasInfoIcon };
}

// ---------------------------------------------------------------------------
// Test
// ---------------------------------------------------------------------------

test.describe("@smoke Revenue-at-Risk parity across pages", () => {
  test(
    "all four pages show the same Revenue-at-Risk value (within $1) and meta tooltip is visible",
    async ({ page }) => {
      await loginAsAdmin(page);

      const pages = [
        { path: "/", label: "dashboard" },
        { path: "/recapture", label: "recapture" },
        { path: "/prospective", label: "prospective" },
        { path: "/reports", label: "reports" },
      ] as const;

      const results: Array<{ label: string; dollars: number; hasInfoIcon: boolean }> = [];

      for (const { path, label } of pages) {
        const { dollars, hasInfoIcon } = await collectRevenue(page, path);
        results.push({ label, dollars, hasInfoIcon });
      }

      // ── 1. Every page must surface a parseable dollar value ──────────────
      for (const { label, dollars } of results) {
        expect(
          isNaN(dollars),
          `[${label}] revenue-at-risk-value could not be parsed as a dollar amount`,
        ).toBe(false);
        expect(
          dollars,
          `[${label}] Revenue-at-Risk should be > 0 (single-source-of-truth API must return data)`,
        ).toBeGreaterThan(0);
      }

      // ── 2. All four values must match within $1 rounding tolerance ────────
      const values = results.map((r) => r.dollars);
      const min = Math.min(...values);
      const max = Math.max(...values);

      expect(
        max - min,
        `Revenue-at-Risk values diverge across pages — not wired to the same source.\n` +
          results.map((r) => `  ${r.label}: $${r.dollars.toLocaleString()}`).join("\n"),
      ).toBeLessThanOrEqual(1);

      // ── 3. _meta info icon must be visible on at least one page ───────────
      const pagesWithInfo = results.filter((r) => r.hasInfoIcon).map((r) => r.label);
      expect(
        pagesWithInfo.length,
        "No page exposes a Revenue-at-Risk _meta info icon — transparency proof failed.\n" +
          "Add an `info` prop (StatCard) or `meta` prop (MetricCard) to at least one Revenue-at-Risk card.",
      ).toBeGreaterThanOrEqual(1);
    },
  );
});
