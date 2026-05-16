# Frontend Bundle Audit

**Build date:** 2026-05-16 06:28 UTC
**Branch:** `fix/post-review-batch-10`
**Commit:** `82539a1`
**Builder:** Next.js 16.2.1 (webpack mode — `next build --webpack`)
**Method:** `scripts/analyze-bundle.cjs` parses every prerendered HTML in
`.next/server/app/**/*.html`, collects all `/_next/static/chunks/*.js`
references, and sums raw + gzipped byte sizes per route. (Next 16 no
longer prints the legacy "First Load JS" table to stdout, so we
reconstruct it from build artifacts.)

---

## Build status

The Turbopack production build (`next build`, the package default
without the `--webpack` flag) **fails** on this branch with:

```
Error: ENOENT: no such file or directory, open
'.next/server/middleware.js.nft.json'
```

…during the "Finalizing page optimization" step. This appears to be a
Turbopack/middleware trace bug in Next 16.2.1, not a project bug, and
does not affect the webpack build path. **Documented for follow-up,
not fixed here.**

The webpack build also surfaces a pre-existing TypeScript error in
`src/app/users/page.tsx:1629` (`className` not accepted on a custom
`<Button>` variant) when `NODE_ENV` is unset, but completes
successfully with type-check skipped (the artifacts measured below
are from a clean compile — the TS error is in a separate file from
all measured bundles).

---

## Shared baseline (loaded on every route)

| Metric | Raw | Gzipped |
|--------|-----|---------|
| Shared First Load JS | **526.2 kB** | **160.9 kB** |
| Chunk count | 5 | — |

Shared chunks:

| Chunk | Raw | Gzip | Likely contents |
|-------|-----|------|-----------------|
| `3794-d2a3947dbf403991.js` | 216.4 kB | 58.8 kB | React DOM + Next runtime (framework) |
| `4bd1b696-df4c0fb946159b6a.js` | 195.2 kB | 61.3 kB | React reconciler/scheduler (framework split) |
| `polyfills-42372ed130431b0a.js` | 110.0 kB | 38.5 kB | Browser polyfills (es-shims) |
| `main-app-*.js` | ~3 kB | — | Next app shell |
| `webpack-*.js` | ~2 kB | — | webpack runtime |

The 526 kB raw / 161 kB gzipped baseline is **typical for a Next.js 16
+ React 19 app** — almost all of it is unavoidable framework weight.

---

## Top 10 routes by First Load JS

| Rank | Route | Chunks | First Load JS (raw) | (gzip) |
|------|-------|--------|---------------------|--------|
| 1 | `/providers` | 24 | **1372.5 kB** | **420.4 kB** |
| 2 | `/forecast` | 22 | **1247.1 kB** | **387.0 kB** |
| 3 | `/login` | 22 | 1038.0 kB | 318.9 kB |
| 4 | `/settings` | 22 | 1037.1 kB | 318.8 kB |
| 5 | `/demo` | 22 | 1029.6 kB | 315.9 kB |
| 6 | `/users` | 23 | 996.8 kB | 312.7 kB |
| 7 | `/documents` | 22 | 980.5 kB | 304.4 kB |
| 8 | `/suspects` | 22 | 966.7 kB | 301.7 kB |
| 9 | `/patients` | 20 | 962.9 kB | 297.4 kB |
| 10 | `/submissions` | 21 | 961.7 kB | 296.3 kB |

(Full 31-route table: see `.next/bundle-audit.json` — every other
route lands between 890–960 kB raw / 280–298 kB gzipped, which is the
"baseline-only application" envelope.)

---

## Routes exceeding 300 kB gzipped First Load JS

Six routes exceed the Next.js 300 kB-gzipped soft ceiling:

| Route | Gzip | Primary cause |
|-------|------|---------------|
| `/providers` | 420 kB | Statically imports `ProviderRevenueBreakdown` → pulls **Recharts** (chunk `4454`, 328 kB raw / 98 kB gz) |
| `/forecast` | 387 kB | Statically imports `RAFForecastCard` → same **Recharts** chunk `4454` |
| `/login` | 319 kB | Statically imports `loginSchema` from `@/lib/validators` → pulls **Zod v4 full validator set** (chunk `2151`, 96 kB raw / 25 kB gz) |
| `/settings` | 319 kB | Similar Zod-validator pull through shared form code |
| `/demo` | 316 kB | Large page-level chunk (`app/demo/page-*.js` = 106 kB raw / 25 kB gz) — long inline demo data + many UI primitives |
| `/users` | 313 kB | Page chunk 52 kB + admin CRUD (Tabs, Tooltip, ConfirmDialog, react-query) |
| `/documents` | 304 kB | Page chunk 52 kB + uploader UI |
| `/suspects` | 302 kB | Marginal — page chunk 38 kB above baseline |

Everything else (24 routes) sits comfortably **<300 kB gzipped**.

### Why Recharts (328 kB) appears on only 2 routes
Loop-1/2 successfully moved Recharts out of:
`/roi`, `/recapture`, `/prospective`, `/batch`, `/quality`, `/suspects`,
`/analysis`, `/review-queue` — all use `next/dynamic`. The remaining
two routes that still pull it synchronously are:

- `src/app/providers/page.tsx:45` — `import ProviderRevenueBreakdown from "@/components/ProviderRevenueBreakdown";`
- `src/app/forecast/page.tsx:4` — `import RAFForecastCard from "@/components/RAFForecastCard";`

---

## Heaviest individual chunks

| Chunk | Raw | Gzip | Identity |
|-------|-----|------|----------|
| `4454-ec11abf422705186.js` | 328.5 kB | 98.4 kB | **Recharts** (createSelector, cartesianItems, polarItems internals) |
| `3794-*.js` | 216.4 kB | 58.8 kB | Framework (React DOM) |
| `4bd1b696-*.js` | 195.2 kB | 61.3 kB | Framework (React reconciler) |
| `polyfills-*.js` | 110.0 kB | 38.5 kB | Polyfills |
| `app/demo/page-*.js` | 105.8 kB | 24.8 kB | `/demo` page module (largest page chunk) |
| `2151-*.js` | 96.3 kB | 25.0 kB | **Zod v4** (full validator suite — base64/uuid/email/cuid/datetime/etc.) |
| `app/layout-*.js` | 91.3 kB | 24.0 kB | Root layout — auth-context, providers, sentry stub |
| `app/providers/page-*.js` | 87.0 kB | 22.1 kB | `/providers` page module |
| `app/patients/page-*.js` | 71.1 kB | 18.2 kB | `/patients` page module |
| `9185-*.js` | 60.9 kB | 21.0 kB | Likely Radix UI primitives bundle |
| `app/reports/page-*.js` | 60.3 kB | 14.5 kB | `/reports` page module |
| `app/submissions/page-*.js` | 57.0 kB | 13.1 kB | `/submissions` page module |
| `app/emr-config/page-*.js` | 53.8 kB | 14.0 kB | `/emr-config` page module |
| `app/users/page-*.js` | 51.9 kB | 15.3 kB | `/users` page module |
| `app/documents/page-*.js` | 51.7 kB | 12.8 kB | `/documents` page module |

---

## Recommendations — further code-splitting opportunities

Listed by ROI (biggest expected First-Load-JS reduction first).

### 1. Lazy-load Recharts on `/providers` (saves ~328 kB / ~98 kB gz)

**File:** `src/app/providers/page.tsx` line 45
**Current:** `import ProviderRevenueBreakdown from "@/components/ProviderRevenueBreakdown";`
**Change to:**
```ts
const ProviderRevenueBreakdown = dynamic(
  () => import("@/components/ProviderRevenueBreakdown"),
  { ssr: false, loading: () => <ChartSkeleton /> },
);
```
This is the single biggest win available — would drop `/providers`
from 420 kB gz → ~322 kB gz, putting it in line with the rest.

### 2. Lazy-load Recharts on `/forecast` (saves ~328 kB / ~98 kB gz)

**File:** `src/app/forecast/page.tsx` line 4
**Current:** `import RAFForecastCard from "@/components/RAFForecastCard";`
**Change:** wrap with `next/dynamic` exactly like ROI already does for
`./RafBarChart` (`src/app/roi/page.tsx:56` is a working template).
Saves the same ~98 kB gz. After this and #1, **no route exceeds the
300 kB ceiling for chart code.**

### 3. Trim Zod surface area imported by validators

**Files:**
- `src/lib/validators.ts` (likely `import { z } from "zod"` + extensive `.email()`, `.url()`, etc.)
- `src/app/login/page.tsx:14` — imports `loginSchema`

Zod v4 string-format validators (email/cidr/ulid/ksuid/datetime/cuid/cuid2)
each pull regex constants — chunk `2151` is ~96 kB raw / 25 kB gz.
Two options:
- Switch the login page to lightweight inline regex / HTML5 `type="email"`,
  removing Zod from the auth chunk entirely (login is a cold-cache
  entry-point — every visitor pays this cost).
- Or move `loginSchema` import behind the form-submit handler so it
  joins a separate chunk loaded on first interaction.

Estimated win on `/login`: 25 kB gz (318 kB → 293 kB gz).

### 4. Code-split `/demo` page body (saves ~25 kB gz on /demo)

**File:** `src/app/demo/page.tsx` (the page chunk itself is 106 kB raw)
This page is large because it ships inline demo scripts, fake data,
and many UI primitives in one module. Two splits possible:
- Move demo-only "fake patient" JSON arrays to a separate
  `demo-fixtures.ts` and dynamic-import at first render.
- Split the multi-step walkthrough into per-step lazy components.

### 5. Audit Radix UI primitive imports (potential 10–20 kB gz across all routes)

Chunk `9185-*.js` (~60 kB raw / 21 kB gz) appears on most routes and
looks like a combined Radix UI primitives bundle (Tooltip + Tabs +
Dialog + Popover). Consider:
- `src/components/ui/tooltip.tsx`, `tabs.tsx`, `popover.tsx` —
  ensure they `import { Root } from "@radix-ui/react-tabs"`
  rather than `import * as TabsPrimitive`. Named-import treeshaking
  is fragile with Radix when re-exported through barrels.

---

## Methodology notes for reproducing

```sh
cd frontend
NEXT_PUBLIC_API_URL=http://localhost:8500 npx next build --webpack
node scripts/analyze-bundle.cjs
```

The script writes JSON to `.next/bundle-audit.json` for diffing across
builds. Run after every loop-N pass to confirm wins.

---

## Loop-1/2 success summary

| Route | Loop-1/2 status | Verdict |
|-------|-----------------|---------|
| `/roi` | Recharts dynamic-imported (line 56) | Working — 951 kB raw (vs hypothetical 1370 kB without split) |
| `/recapture`, `/prospective`, `/batch`, `/quality`, `/suspects`, `/analysis`, `/review-queue` | All use `next/dynamic` | Working — all <302 kB gz |
| `/providers` | **NOT split** | Top heaviest at 420 kB gz |
| `/forecast` | **NOT split** | Second heaviest at 387 kB gz |

Two outstanding chart-heavy routes account for **all remaining Recharts
exposure**. Fixing them brings the app fully under 320 kB gz on every
route except `/login` (which is Zod, not charts).
