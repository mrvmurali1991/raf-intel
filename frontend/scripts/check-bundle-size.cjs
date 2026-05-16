#!/usr/bin/env node
/**
 * check-bundle-size.cjs
 *
 * Reads .next/bundle-audit.json produced by analyze-bundle.cjs and
 * enforces per-route gzip budgets.
 *
 * Budgets (gzip bytes):
 *   ≤ 250 kB  — lightweight shell routes: /, /login, /patients, /review-queue
 *   ≤ 350 kB  — all other routes (dashboard, forecast, providers, settings, etc.)
 *
 * Why 350 kB ceiling for the rest:
 *   Loop-2 audit showed /forecast hitting 420 kB and /providers 380 kB before
 *   loop-3 lazy-loading fixes. 350 kB locks in that regression floor while
 *   leaving a 30 kB safety margin over the post-fix measurements.
 *
 * Exits 0 if all routes pass, 1 if any route exceeds its budget.
 */

'use strict';

const fs   = require('fs');
const path = require('path');

const AUDIT_FILE = path.resolve(__dirname, '../.next/bundle-audit.json');

// --- Budgets -----------------------------------------------------------
const KB = 1024;

// Strict budget for routes that should be lean entry points
const STRICT_BUDGET_GZ = 250 * KB;
const STRICT_ROUTES = new Set(['/', '/login', '/patients', '/review-queue']);

// Default budget for all other routes
const DEFAULT_BUDGET_GZ = 350 * KB;

function budgetFor(route) {
  return STRICT_ROUTES.has(route) ? STRICT_BUDGET_GZ : DEFAULT_BUDGET_GZ;
}

// --- Load audit -------------------------------------------------------
if (!fs.existsSync(AUDIT_FILE)) {
  console.error(`[check-bundle-size] ERROR: ${AUDIT_FILE} not found.`);
  console.error('Run `node scripts/analyze-bundle.cjs` after `next build` first.');
  process.exit(1);
}

const audit = JSON.parse(fs.readFileSync(AUDIT_FILE, 'utf8'));
const rows  = audit.rows;

if (!Array.isArray(rows) || rows.length === 0) {
  console.error('[check-bundle-size] ERROR: bundle-audit.json has no route rows.');
  process.exit(1);
}

// --- Check & report ---------------------------------------------------
const COL = { route: 40, gz: 12, budget: 12, status: 8 };

function pad(s, n) { return String(s).padEnd(n); }
function fmt(bytes) { return (bytes / KB).toFixed(1) + ' kB'; }

const header =
  pad('Route', COL.route) +
  pad('Gzip', COL.gz) +
  pad('Budget', COL.budget) +
  pad('Status', COL.status);

const divider = '-'.repeat(COL.route + COL.gz + COL.budget + COL.status);

console.log('\n== Bundle Size Gate ==');
console.log(divider);
console.log(header);
console.log(divider);

let failures = 0;

// Sort: failures first, then alphabetical
const sorted = [...rows].sort((a, b) => {
  const aFail = a.gzTotal > budgetFor(a.route);
  const bFail = b.gzTotal > budgetFor(b.route);
  if (aFail !== bFail) return aFail ? -1 : 1;
  return a.route.localeCompare(b.route);
});

for (const r of sorted) {
  const budget = budgetFor(r.route);
  const over   = r.gzTotal > budget;
  if (over) failures++;
  const status = over ? 'FAIL' : 'pass';
  const line =
    pad(r.route, COL.route) +
    pad(fmt(r.gzTotal), COL.gz) +
    pad(fmt(budget), COL.budget) +
    pad(status, COL.status);
  console.log(line);
}

console.log(divider);

if (failures > 0) {
  console.error(`\n[check-bundle-size] FAILED: ${failures} route(s) exceed their gzip budget.`);
  console.error('Fix: lazy-load heavy components, move them behind dynamic imports, or');
  console.error('     split large dependencies into separate chunks.\n');
  process.exit(1);
} else {
  console.log(`\n[check-bundle-size] All ${sorted.length} routes within budget.\n`);
  process.exit(0);
}
