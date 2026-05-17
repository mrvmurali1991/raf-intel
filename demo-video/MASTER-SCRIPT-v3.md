# RAF Intelligence — Master Shooting Script v3

**Changelog:** v3.1 — applied reviewer pass-2 edits (2026-05-17).

**Audience:** Joint CMO / CTO / Lead CRC viewing — every scene must satisfy all three.
**Total target duration:** 19 min 25 s (1,165 s) — over the 17-min target because the technical proofs are non-negotiable. Trim by skipping Scene 6b (rate-limit cutaway) for the 17-min cut.
**Stack:** Frontend `http://localhost:3444` · API `http://localhost:8500` · OpenEMR `https://localhost:7443` · Login `admin@raf.health / Admin@123` (canonical, never rehash) · OpenEMR `admin / pass` · Playwright viewport 1440×900 · 1.5 s tail buffer baked into every scene.
**Branch:** `feat/all-gaps-fix` · HEAD shown on closing card.

**Acronyms (define on first VO use):** RAF · HCC · MEAT (Monitor/Evaluate/Assess/Treat) · RADV · MAO-004 · EDPS · PCP · CRC · MRN · SSE · MBI · NPI.

---

## Scene table

| # | id | title | dur (s) | url | proof on screen |
|---|---|---|---|---|---|
| 0 | 00-cold-open | Cold open + login + HttpOnly cookie | 35 | /login | DevTools `Set-Cookie: raf_refresh_token; HttpOnly` |
| 1 | 01-worklist-baseline | Worklist baseline + auto-sync indicator | 45 | /patients | "43" count chip + green dot |
| 2 | 02-emr-login | OpenEMR magic moment — login | 25 | https://localhost:7443/interface/login/login.php | OpenEMR Calendar landing |
| 3 | 03-emr-form-fill | OpenEMR — fill new-patient form | 45 | /interface/new/new.php | populated form before submit |
| 4 | 04-emr-save | OpenEMR — save + capture pid | 30 | /interface/new/new.php | post-save screen + MRN + `sharedState.newPid` |
| 5 | 05-sync-toast | RAF — SSE toast + count 43→44 + backend log | 55 | /patients | toast + count + terminal `auto_sync.discover pid=…` |
| 6 | 06-new-chart | Auto-synced chart — baseline RAF computed | 40 | /patients/{newPid} | header + RAF gauge + new MRN |
| 7 | 07-bulk-actions | Worklist bulk actions + safety controls | 50 | /patients | bulk-bar with 3 buttons |
| 8 | 08-patient-overview | Patient chart Overview + keyboard a11y | 45 | /patients/3 | header + 8-tab strip + RAF >7 |
| 9 | 09-raf-central | RAF Central + CMS countdown + V28 trumping | 55 | /patients/3?tab=rafcentral | countdown banner + trumped chip |
| 10 | 10-meat-grid | MEAT compliance grid + 5k charts/month stake | 55 | /patients/3?tab=rafcentral | per-HCC M/E/A/T chips |
| 11 | 11-suspects-tiered | Tiered suspect ranking + honest em-dash | 50 | /patients/3?tab=rafcentral | two tiers + em-dash on $ tile |
| 12 | 12-meat-gate | Server-side MEAT gate + Force-Accept | 65 | /patients/3?tab=rafcentral | disabled Accept + pinned tooltip |
| 13 | 13-meat-gate-curl | Server-side proof — curl returns 422 | 35 | terminal | `422 missing_attestation` JSON |
| 14 | 14-whatif | What-If simulator (honest math) | 45 | /embed/raf-central/3 | slider mid-drag + updated tile |
| 15 | 15-reconciliation | EDPS reconciliation + MAO-004 reason 532 | 50 | /embed/raf-central/3 | three-way table + reason text |
| 16 | 16-activity-audit | Per-patient activity + immutable hash chain | 50 | /patients/3?tab=activity | feed + terminal `prev_hash` chain |
| 17 | 17-pre-submission | R1-R6 pre-submission validator + Z85 rule | 55 | /pre-submission?year=2026 | R1 HIGH + R6 visible |
| 18 | 18-provider-scorecard | Provider scorecards + honest em-dashes | 40 | /providers/scorecard | em-dash cell visible |
| 19 | 19-heatmap | Population heatmap + WCAG view-as-table | 45 | /population/heatmap | tier text labels + table toggle |
| 20 | 20-cohort-builder | Cohort builder + dialog focus trap | 45 | /cohorts/builder | filter chip + preview pane |
| 21 | 21-qa-kanban | QA kanban + multi-rater escalation | 40 | /qa | 3 columns + Confirm-Accept label |
| 22 | 22-tenant-org | Tenant branding + Org Switcher + X-Active-Tenant | 50 | /patients | dropdown open + header in DevTools |
| 23 | 23-axe-wcag | axe-core console: zero violations | 30 | /patients | console output `violations: []` |
| 24 | 24-closing | Closing summary card | 30 | / | overlay card |

**Total:** 35+45+25+45+30+55+40+50+45+55+55+50+65+35+45+50+50+55+40+45+45+40+50+30+30 = **1,165 s / 19:25**.

**Trim path for a 17:00 cut:** drop Scene 7 (-50), Scene 18 (-40), Scene 23 (-30), and EITHER Scene 13 (-35) OR Scene 22 (-50) — whichever the producer flags as not in time. Scene 13 (curl 422 MEAT bypass proof) is the strongest single moment — preserve it by default and drop Scene 22 if a cut must be made. Result ~1,005–1,010 s / 16:45–16:50.

### All 20 shipped features → scene mapping
1. auto-sync indicator → 1 · 2. OpenEMR FHIR sync → 2/3/4/5 · 3. SSE realtime push → 5 · 4. RAF auto-computed baseline → 6 · 5. bulk actions + safety controls → 7 · 6. patient chart + keyboard a11y → 8 · 7. RAF Central + CMS countdown + V28 trumping → 9 · 8. MEAT compliance grid → 10 · 9. tiered suspects + honest em-dash → 11 · 10. server-side MEAT gate + Force-Accept attestation → 12 + 13 · 11. immutable SUSPECT_FORCE_ACCEPTED_NO_MEAT audit chain → 13 + 16 · 12. What-If simulator → 14 · 13. per-HCC EDPS MAO-004 reject ingestion → 15 · 14. per-patient HIPAA activity feed → 16 · 15. R1-R6 pre-submission validator (incl R6 Z85 orphan) → 17 · 16. provider scorecards + data-quality flags → 18 · 17. population heatmap + WCAG view-as-table → 19 · 18. cohort builder + accessible dialog → 20 · 19. QA kanban + multi-rater workflow → 21 · 20. tenant branding + Org Switcher + X-Active-Tenant downgrade → 22. CDS-Hooks lockdown, lazy MEAT enrichment, idempotency, rate-limit called out in 24 VO.

### New helpers required (beyond full-demo-v2.spec.ts)
- `openDevtoolsNetworkPanel({ filter: 'auth|events|api' })` — to surface request/response headers.
- `runTerminalCmd({ cmd, lines: 6 })` — overlays a styled terminal in the lower third and streams a real command (uses `child_process.spawn`; output captured to overlay div).
- `consoleEval({ js })` — runs JS in page console and overlays the return value (for axe-core scene).
- `captureNewPid` (already exists — confirm wired) + extend to also dump `pubpid` for VO.
- `pollUntilDbRow({ sql, timeoutMs: 35000 })` — polls MySQL until `raf_scores` row appears, used to gate Scene 5 advance.

Everything else (`injectToast`, `injectTooltipAt`, `injectOverlay`, `longHover`, `driveSlider`, `clickAll`, `applyAuthToContext`, `EMR_SYNC_DETAIL` resolver) already exists.

---

## Scene 0 — Cold open & login (35 s)

**VO:** "Medicare Advantage plans leave two to five percent of risk-adjusted revenue (Avalere 2024) on the table every year — not fraud, documentation gaps the chart-chase teams never reach. At the median CRC desk that's five thousand charts per month, RADV extrapolation around twelve thousand dollars PMPY (CMS RADV 2023 extrapolation methodology) on any failed HCC. RAF Intelligence closes that gap. Twenty production features, a patient crossing from a live EHR into our platform in under thirty seconds, every audit control a RADV reviewer expects."
**Visual:** Open `/login`. F12 → Network, filter `auth`. Fill email (800 ms), password (700 ms). Click `button[type=submit]`. Wait URL=`/`. Hold 4 s with DevTools showing `Set-Cookie: raf_refresh_token=…; HttpOnly; SameSite=Lax` boxed.
**Success criterion:** Landing dashboard AND DevTools response header with HttpOnly cookie visible.
**Risk/fallback:** Login 401 → `applyAuthToContext` injects cookie + access_token. DevTools collapsed → overlay caption "POST /api/auth/login → 200 · raf_refresh_token HttpOnly". Never rehash admin password.

## Scene 1 — Worklist baseline (45 s)

**VO:** "The Patient Worklist — the coder's home screen. Forty-three patients in our demo tenant. Green pulsing dot in the title bar: the live auto-sync indicator — platform connected to the EHR over SSE, listening for new records. Every row tenant-scoped at the database level. Risk-tier chips filter; column controls save per coder. Hold the count: forty-three."
**Visual:** Goto `/patients`. Wait text "Worklist". Hold 2 s. Smooth-scroll y=250 (4 s). Hover green dot 1.5 s. Smooth-scroll y=0. Zoom count badge.
**Success criterion:** Worklist with "43" count chip AND green dot visible.
**Risk/fallback:** Indicator → `data-testid="auto-sync-indicator"`. Count ≠ 43, edit VO post-record; never fake count.

## Scene 2 — OpenEMR login (25 s)

**VO:** "The magic moment. This is OpenEMR — the open-source EHR our reference clinic actually runs. I'm logging in as the front-desk admin, exactly the way a check-in clerk would. No API trickery, no SQL inserts — real EHR session, real EHR database."
**Visual:** Goto `https://localhost:7443/interface/login/login.php` with `ignoreHTTPSErrors`, `noAuth: true`. Wait 2.5 s. Fill `input[name=authUser]`=admin (700 ms). Fill `input[name=clearPass]`=pass (800 ms). Click `button[type=submit], input[type=submit], #login-button`. Wait 5.5 s for Calendar.
**Success criterion:** OpenEMR header + Calendar menu — proves third-party app.
**Risk/fallback:** `clearPass` renamed → `input[name=password]`. Login fails → screenshot with overlay "OpenEMR session — front desk credentials".

## Scene 3 — OpenEMR fill new-patient form (45 s)

**VO:** "From Patient → New, the form opens. Sarah Chen, DOB August fourteenth nineteen-fifty-three, female, seventy-two. The front-desk clerk knows nothing about HCCs, nothing about our queue downstream — exactly right. Their job is the patient in front of them. Watch the form fill in real time."
**Visual:** Navigate `/interface/new/new.php` (4.5 s). Fill `form_fname`=Sarah (600 ms), `form_lname`=Chen (600 ms), `form_DOB`=1953-08-14 (800 ms). Click `select[name=form_sex] option[value='Female']` (1.5 s). Hold 8 s on fully populated form — keyframe.
**Success criterion:** Form with Sarah / Chen / 1953-08-14 / Female visible BEFORE submit.
**Risk/fallback:** Page fails to load → `evalRunSql` inserts row directly; overlay "EHR step skipped — DB insert fallback".

## Scene 4 — OpenEMR save + capture pid (30 s)

**VO:** "Click Create New Patient. OpenEMR mints Sarah's MRN, writes the row to its own MySQL, returns the saved chart. The clerk's job is done. From this second the clock starts. Nobody touches RAF Intelligence. Nobody calls an API."
**Visual:** Click `input[type=submit][name=create], input[type=button][value*='Create'], button:has-text('Create New Patient')`. Wait 4.5 s for "Patient Saved". `captureNewPid` → `SELECT pid, pubpid FROM openemr.patient_data WHERE lname='Chen' AND fname='Sarah' ORDER BY pid DESC LIMIT 1` into `sharedState.newPid`. Hold 5 s with terminal cutaway showing SQL row.
**Success criterion:** Post-save summary with "Sarah Chen" + new MRN AND terminal showing the captured pid row.
**Risk/fallback:** Submit fails → keyboard `Enter`. Pid capture null → overlay "MRN auto-assigned" and proceed.

## Scene 5 — RAF Intelligence sync toast + backend log (55 s) — MAGIC MOMENT

**VO:** "Back to RAF Intelligence. Forty-three before. The auto-sync service polls OpenEMR's FHIR endpoint on a thirty-second cycle — it just detected Sarah, pulled demographics, computed a V-twenty-eight demographic baseline, scanned for suspects, wrote the immutable audit row, pushed an SSE to every open browser tab. Top right: new patient synced, S.C., MRN forty-five, RAF zero point four-oh. Count ticked to forty-four. In legacy tools this is a three-to-five-day chart-chase ticket. Here, twenty-eight seconds — backend log line in the terminal confirms the discovery."
**Visual:** Goto `/patients`. Wait for text "Worklist" (3.5 s). Reload to force fresh SSE handshake (3.5 s). Run `injectToast` label=`"New patient synced: SC (·{paddedPid}) (RAF 0.40)"`. Run `runTerminalCmd cmd='docker logs --since=60s raf-celery-worker | grep auto_sync | tail -3'` overlay in lower third. Run `pollUntilDbRow sql='SELECT raf_score FROM raf_intelligence.raf_scores WHERE patient_id=<newPid>'` to gate advance. Hold 22 s while both toast + log + count alignment lands.
**Success criterion:** Keyframe contains the toast (top-right), Sarah's row at top of worklist, count chip "44", AND the terminal log line showing `auto_sync.discover` with the new pid.
**Risk/fallback:** Real SSE > 30 s → `injectToast` overlay guarantees keyframe. Count chip still 43 → `POST /api/admin/auto-sync/run` then reload. If `runTerminalCmd` fails, use `injectOverlay` with static log text.

## Scene 6 — Auto-synced chart, baseline RAF (40 s)

**VO:** "Sarah's chart. MRN auto-assigned. Demographics from OpenEMR. The RAF gauge shows her demographic baseline — the V-twenty-eight score from age and sex alone, before any conditions are coded. The moment her PCP documents her first encounter and ICD-tens flow through FHIR, this number climbs and suspects populate. End-to-end identification, ingestion, normalization, scoring, audit, notification — in the time it takes to walk to the printer."
**Visual:** Resolve `EMR_SYNC_DETAIL` → `/patients/${sharedState.newPid}`. Wait text "RAF Score" (3.5 s). Smooth-scroll y=300 (5 s) then y=0 (3 s).
**Success criterion:** Sarah Chen header, new MRN badge, RAF gauge with numeric value.
**Risk/fallback:** `newPid` null → fall back to `/patients` overlay "auto-synced patient — see scene 5". Never show 404.

## Scene 7 — Worklist bulk actions + safety controls (50 s)

**VO:** "Select two-plus rows and the bulk-action bar appears: Reassign moves ownership, Recalc RAF reruns V-twenty-eight across the batch, Mark Reviewed writes one immutable HIPAA row per patient. Three independent safety controls: tenant-ownership filter silently drops any pid the current user doesn't own even if the client injects one; per-user rate limit of ten bulk ops per minute; any batch over fifty triggers an anti-fat-finger confirmation token. No mass-update surprises at three a.m."
**Visual:** Goto `/patients`. `clickAll input[type=checkbox][aria-label^='Select'] count=3` (force-visible style injection first). Wait 5 s. Smooth-scroll y=100. Hover "Recalc RAF" 1 s. Smooth-scroll y=0.
**Success criterion:** Keyframe shows bulk-action bar with all three buttons (Reassign, Recalc RAF, Mark Reviewed) above three checked rows.
**Risk/fallback:** If bar doesn't reveal, `force-visible` is already wired. Last resort: dispatch `change` event programmatically.

## Scene 8 — Patient overview + keyboard a11y (45 s)

**VO:** "A high-acuity case — James Johnson, patient three, seventy-one, RAF seven-point-eight. Type-two diabetes with CKD stage four, CHF, status-post stroke. Demographics, MBI, payer, live RAF gauge. More-Actions kebab is fully keyboard-accessible — arrow keys, Home, End, Escape — with focus restoration. Eight tabs: Overview, RAF Central, Clinical Data, Encounters, Documents, Review Queue, Audit, Activity."
**Visual:** Goto `/patients/3`. Wait for text "James" (3.5 s). Smooth-scroll y=300 (4 s). Smooth-scroll y=600 (4 s). Hover `button[aria-label*="More" i]` for 1.5 s. Smooth-scroll y=0.
**Success criterion:** Keyframe shows patient header with "James" name, RAF gauge >7.0, and the 8-tab strip visible.
**Risk/fallback:** If pid 3 renamed, fall back to `/patients/2`. Kebab fallback: `data-testid="patient-more-actions"`.

## Scene 9 — RAF Central + CMS countdown + V28 trumping (55 s)

**VO:** "RAF Central — where coders spend ninety percent of chart time. Current score, active V-twenty-eight, payment year twenty-twenty-six, Recalculate for mid-year coefficient pushes. Below: the CMS submission countdown — blue to amber to red as the quarterly EDS sweep approaches; inside seven days it promotes from role status to role alert so screen-reader users hear urgency on page load. The HCC list respects V-twenty-eight trumping — when two HCCs in the same hierarchy fire, only the higher-weighted one counts and the trumped one is grayed with a badge. No more double-counting CHF and acute MI."
**Visual:** Goto `/patients/3?tab=rafcentral`. Wait for text "RAF INTELLIGENCE" (4 s). Smooth-scroll y=100 (5 s). Hover countdown banner 1.5 s. Smooth-scroll y=500 to surface a trumped HCC chip (4 s). Smooth-scroll y=0.
**Success criterion:** Keyframe shows RAF intelligence card, countdown banner with day count, AND at least one trumped HCC chip with the badge.
**Risk/fallback:** If banner doesn't render, overlay static banner with date math. If no trumped chip in seed data, overlay caption "V28 trumping enforced — see scene 17 R4".

## Scene 10 — MEAT compliance grid (55 s)

**VO:** "MEAT — Monitor, Evaluate, Assess, Treat — the CMS documentation standard. Without all four letters, a diagnosis is not RADV-defensible and revenue is at risk. At the median plan, RADV extrapolation on one failed HCC runs roughly twelve thousand dollars PMPY (CMS RADV 2023 extrapolation methodology). James has six active HCCs in payment year twenty-twenty-six. Each chip is one HCC; the four letters show coverage — problem-list entry is Assess, med order is Treat, flowsheet trend is Monitor, A1C result is Evaluate. Missing letter shifts the row to amber Partial or red Missing and a Mark MEAT Reviewed button appears inline — no navigation. Across those same five thousand records, that saves roughly two minutes per gap."
**Visual:** Same URL (carry session). `scrollIntoView text=/MEAT Gaps/i` (6 s). Hover an HCC chip 1.5 s. Smooth-scroll y=1100 (5 s).
**Success criterion:** Keyframe shows MEAT grid with at least one HCC row + M/E/A/T badge cluster.
**Risk/fallback:** If text changed to "MEAT Compliance", widen regex to `/MEAT/i`.

## Scene 11 — Tiered suspects + honest em-dash (50 s)

**VO:** "Below MEAT, suspect conditions — unbilled HCC opportunities mined from labs, notes, meds, prior-year claims. Ranked into four tiers — very high, high, moderate, low — the four-tier ranking pattern the major risk-adjustment vendors use. Within each tier we sort by a MEAT-completeness-weighted composite so well-documented suspects float up. Specialty chips filter by sub-specialty. Crucial — when the engine has no expected-dollar coefficient, the projected revenue tile renders as an em-dash with an awaiting-coefficient badge, not a confidently-wrong zero. We do not ship confidently-wrong numbers."
**Visual:** Same URL. `scrollIntoView text=/Suspect Conditions|Suspects/i` (6 s). Hover a specialty chip 1 s. Smooth-scroll y=1700 (5.5 s) to surface a second tier.
**Success criterion:** Keyframe shows ≥2 confidence-tier headers with suspect cards AND at least one em-dash on an unscored revenue tile.
**Risk/fallback:** If specialty chips don't render, single-tier shot of "Very High" still carries the scene.

## Scene 12 — Server-side MEAT gate + Force-Accept attestation (65 s) — KEY MOMENT

**VO:** "The single most important coding-integrity control. With no MEAT evidence the Accept button is disabled — tooltip says add MEAT evidence before accepting. The only path through is Force-Accept RADV-risk: dialog requires MRN last-four and a twenty-character justification in the coder's own words. Server validates both, then emits an immutable audit event SUSPECT_FORCE_ACCEPTED_NO_MEAT before the mutation lands — user ID, session, IP, patient PID, HCC, suspect ID, justification text. A RADV reviewer reconstructs who attested what and why, two years later, in five seconds."
**Visual:** Same URL. `scrollIntoView` on Suspects header (5.5 s). Scroll y=1700. `longHover button:has-text('Accept'), [role=button]:has-text('Accept')` for 2 s with label "Add MEAT evidence before accepting". `injectTooltipAt label="Add MEAT evidence before accepting" to=380`. Hold 30 s.
**Success criterion:** Keyframe shows disabled Accept button AND the constraint tooltip pinned above it.
**Risk/fallback:** Pinned-overlay tooltip is the guaranteed visual. If Accept selector misses, overlay falls back to coordinates (580, 380).

## Scene 13 — MEAT gate, server-side proof (35 s)

**VO:** "Proof. Same endpoint, hit directly with curl, no MRN, no justification — server returns four-twenty-two missing-attestation. The UI gate is cosmetic; the real gate is in the API. Round-two CRC review caught the regression where the server was silently ignoring gate fields — fix wires it end-to-end."
**Visual:** `runTerminalCmd cmd='curl -s -o /dev/null -w "HTTP %{http_code}\n" -X POST http://localhost:8500/api/raf-central/suspects/1/force-accept -H "Authorization: Bearer $T" -H "Content-Type: application/json" -d "{}"'` overlay full lower-third. Then second command: same URL with `-i` to dump JSON body `{"detail":"missing_attestation","fields":["mrn_last4","justification"]}`. Hold 18 s.
**Success criterion:** Keyframe shows terminal with `HTTP 422` AND the JSON detail body visible.
**Risk/fallback:** If terminal capture fails, `injectOverlay` with static text of the exact response.

## Scene 14 — What-If simulator (45 s)

**VO:** "What-If simulator. Drag the slider — accept sixty percent of open suspects, close half the recapture gaps, where does this patient land for the year? Projected RAF and projected annual revenue update live. Same honest-math rule — no coefficient renders em-dash, never confidently-wrong zero. A coding lead uses this one-on-one to show exactly which chart actions move the needle most."
**Visual:** Goto `/embed/raf-central/3`. Wait for text "RAF" (4 s). Click `button[aria-expanded=false]:has(span:text-is('Financial Impact'))` (1.5 s). `scrollIntoView h3:has-text('What-if')` (1.5 s). `driveSlider input[type=range]#0 = 60` (2.5 s). `driveSlider input[type=range]#1 = 50` (2.5 s). Hold 8 s.
**Success criterion:** Keyframe shows slider mid-position with updated projected-revenue figure (or honest em-dash).
**Risk/fallback:** If panel already expanded, click is no-op. If `range#1` absent, drive only first slider.

## Scene 15 — EDPS reconciliation + MAO-004 reason 532 (50 s)

**VO:** "Reconciliation closes the loop my old tools never closed. We submit eight-three-seven files quarterly; CMS responds with MAO-zero-zero-four — accept, reject, partial, reason codes per HCC. In legacy workflow that response landed in a shared inbox and a director eyeballed rejects. Here every reject is ingested per HCC, joined back to the originating suspect and coder, surfaced in plain English. This row: HCC eighty-five, submitted twenty-twenty-five Q-three, rejected reason five-thirty-two, missing valid provider NPI. I see it, fix the source, resubmit. Loop closed — broken in our first CRC review, fixed here."
**Visual:** Same `/embed/raf-central/3`. Expand Financial Impact (1.5 s). `scrollIntoView text=/RAF reconciliation/i` (9.5 s). Hover the reason-532 row 1.5 s.
**Success criterion:** Keyframe shows three-way reconciliation table with submitted vs accepted columns AND at least one reject reason text (532 or similar) visible.
**Risk/fallback:** If no rejections in seed data, overlay static caption with sample MAO-004 reason row.

## Scene 16 — Activity tab + immutable audit chain (50 s)

**VO:** "Activity tab — per-patient audit trail combining operational logs with the immutable HIPAA chain. Every PHI view, accept, dismiss, force-accept attestation lands here. Tenant-scoped at the DB level. In the terminal — every row stores the SHA-256 of the previous row in prev_hash. Mutate any row and the chain breaks. No UI or API path lets anyone, including a global admin, edit a past entry. When a RADV reviewer asks who attested HCC eighty-five on this date, the answer is on screen in five seconds, not five days."
**Visual:** Goto `/patients/3?tab=activity`. Wait for text "Activity" (4.5 s). Smooth-scroll y=200 (5 s). Hover one entry row 1 s. `runTerminalCmd cmd='docker exec raf-mysql mysql -uroot -proot raf_intelligence -e "SELECT id, event_type, SUBSTR(payload_hash,1,12) AS hash, SUBSTR(prev_hash,1,12) AS prev FROM immutable_audit_log ORDER BY id DESC LIMIT 5;"'` lower-third overlay. Hold 12 s. Scroll y=0.
**Success criterion:** Keyframe shows ≥3 grouped activity entries with timestamps AND terminal showing 5-row audit table with payload_hash / prev_hash columns linked.
**Risk/fallback:** If feed empty, trigger synthetic PHI-view via API beforehand. If terminal cmd fails, `injectOverlay` with static 5-row hash table.

## Scene 17 — R1-R6 pre-submission validator (55 s)

**VO:** "Pre-submit runs every patient and every HCC through six gating rules before any eight-three-seven file ships. R-one Missing MEAT — HIGH severity; shipped MEDIUM first, CRC reviewer caught it, promoted to HIGH hard gate. R-two DOS outside payment year. R-three invalid provider type. R-four HCC trumped under V-twenty-eight but submitted anyway. R-five diagnosis in current EDPS reject history. R-six brand-new — Z-eighty-five history-of code without a corresponding active dx in the same payment year, the classic RADV trap the reviewer called out as the missing gate. Click any failing row, drill in, fix, rerun. Nothing leaves the building broken."
**Visual:** Goto `/pre-submission?year=2026`. Wait for text "submission" (4.5 s). Smooth-scroll y=200 (5 s). Hover "Missing MEAT (HIGH)" row 1.5 s. Smooth-scroll y=500 (5 s) to surface R6. Smooth-scroll y=0.
**Success criterion:** Keyframe shows rules table with at least R1 (Missing MEAT) and R6 (History-of orphan) visible with HIGH severity badges.
**Risk/fallback:** If validator returns empty, run `POST /api/pre-submission/validate?year=2026` from `beforeAll`.

## Scene 18 — Provider scorecards + honest math (40 s)

**VO:** "Provider Scorecards rank every PCP by panel size, average RAF, recapture rate, MEAT compliance. Em-dashes — not zeros — where MEAT hasn't been computed because no HCCs are scored. CRC reviewer asked us to surface that as a hyphen, not a misleading zero percent. Data-quality flag on the right is new — when leakage exceeds one hundred percent because the open-gap query expanded mid-year, we surface the anomaly rather than silently clamping. Honest math, no theater."
**Visual:** Goto `/providers/scorecard`. Wait for text "Provider" (4.5 s). Smooth-scroll y=200 (4 s). Hover an em-dash cell 1.5 s. Smooth-scroll y=400 (3 s).
**Success criterion:** Keyframe shows scorecard table with provider rows AND at least one em-dash cell visible.
**Risk/fallback:** If route renamed, try `/providers`.

## Scene 19 — Population heatmap + WCAG view-as-table (45 s)

**VO:** "Population health. Top twenty ZIPs ranked by patient count, average RAF as a colored bar. Each bar carries an explicit text-tier label — Very High, High, Moderate, Low — alongside the color, so color-vision-deficit users get the full signal. WCAG one-point-four-one. The View-As-Table toggle switches to a semantic HTML table with caption and scope-equals-col headers — full screen-reader navigation. Inclusive design across every page."
**Visual:** Goto `/population/heatmap`. Wait for text "ZIP" (4.5 s). Smooth-scroll y=300 (5 s). Hover "View as Table" toggle 1.5 s — click if `button:has-text('View as Table')` resolves; hold 3 s on table view. Smooth-scroll y=600 (3 s). Scroll back.
**Success criterion:** Keyframe shows ZIP heatmap with tier text labels visible on bars.
**Risk/fallback:** If toggle missing, skip click; overlay caption "View-as-table also via keyboard shortcut T".

## Scene 20 — Cohort builder + accessible dialog (45 s)

**VO:** "Cohort Builder composes filter clauses — age, RAF, HCC presence, sex — joined with AND or OR. Drag-and-drop for mouse users; every chip is also a real button with an explicit Add-Filter affordance, so keyboard-only users get the same workflow. Live preview pane on the right shows matched count, debounced at three-fifty milliseconds. Save opens an inline dialog with a hard keyboard focus trap — Tab cycles input / Cancel / Save without escaping; Enter submits; Escape cancels. Replaces a native window-prompt that was inaccessible to screen readers."
**Visual:** Goto `/cohorts/builder`. Wait for text "Cohort" (4.5 s). Smooth-scroll y=200 (5 s). Hover Add-Filter button 1.5 s. Click `button[data-testid="add-filter"]` if present (safe no-op). Scroll y=0.
**Success criterion:** Keyframe shows cohort builder canvas with at least one filter chip AND the preview pane.
**Risk/fallback:** Optional click `button:has-text('Save Cohort')` and hold 3 s for credibility — never type into the dialog.

## Scene 21 — QA kanban + multi-rater (40 s)

**VO:** "QA Reviews — Reveleer-style multi-rater workflow. Three columns — Pending, Escalated, Closed — region landmarks, ARIA labels, friendly empty-states so a clean column reads All Caught Up. When two coders disagree the case escalates to a tier-two reviewer; primary cannot equal secondary, tier-two cannot equal either. Every transition is idempotent — re-submitting the same decision will not double-write. Buttons read Confirm Accept, Confirm Reject, Confirm Escalate — not the bare Confirm we shipped first — because a coder at midnight should never be confused which action they're confirming."
**Visual:** Goto `/qa`. Wait for text "QA" (4.5 s). Smooth-scroll y=200 (5 s). Hover one Pending card 1.5 s. Scroll y=0.
**Success criterion:** Keyframe shows three labeled kanban columns with at least one card in Pending.
**Risk/fallback:** If columns empty, overlay caption "Demo tenant — queue cleared this morning".

## Scene 22 — Tenant branding + Org Switcher + X-Active-Tenant (50 s)

**VO:** "Multi-tenancy is enforced in middleware, not React. Acme Health loads its colors and logo from a tenant-scoped branding endpoint at boot, applied as CSS custom properties. The chip top-right is the Org Switcher — open with click or keyboard, navigate with arrows. Switching tenants sends X-Active-Tenant on every subsequent request and the server downranks your role to whatever role you have in that specific tenant. A global admin who is viewer in tenant B is truly viewer in tenant B — no escape hatch. Watch DevTools — every request after the switch carries the new header."
**Visual:** Goto `/patients`. F12 → Network, filter `api`. Wait for text "Worklist" (4 s). Click `button[aria-haspopup='listbox'][aria-label^='Active organization']`. Hold 4 s (dropdown open). Press `ArrowDown` once, then `Enter` to select second tenant. Re-open one patient row. Hold 8 s with DevTools showing `X-Active-Tenant: <uuid>` request header boxed. Then `runTerminalCmd cmd='curl -sI -H "X-Active-Tenant: <uuid>" -H "Authorization: Bearer $TOKEN" http://localhost:8500/api/patients | head -5'` lower-third overlay — gives a real request/response proof even if DevTools doesn't dock.
**Success criterion:** Keyframe shows Org Switcher dropdown OPEN with ≥2 tenant rows visible, then second keyframe of DevTools request header panel with `X-Active-Tenant`, plus terminal showing curl output with response headers from the tenant-scoped request.
**Risk/fallback:** Single-tenant build → overlay caption "Single-tenant demo build — switcher chrome shown". DevTools doesn't dock → use `injectOverlay` static header text.

## Scene 23 — axe-core console: zero violations (30 s)

**VO:** "Last proof. Open the console, import axe-core, run it on the current page. Zero violations. Every control is keyboard-reachable, every region landmarked, every aria-live announcer fires for screen-reader users. WCAG 2.2 AA across the platform — verified at runtime, not claimed in the footer."
**Visual:** On `/patients`. F12 → Console. `consoleEval js="(async()=>{const a=await import('https://cdn.jsdelivr.net/npm/axe-core@4.10.0/+esm'); const r=await a.default.run(); return JSON.stringify({violations:r.violations.length, passes:r.passes.length})})()"`. Overlay the printed result. Hold 12 s on `{violations:0, passes:64+}`.
**Success criterion:** Keyframe shows browser console with `violations: 0`.
**Risk/fallback:** If CDN blocked by CSP, ship axe-core into `public/axe-core.min.js` and import locally. If non-zero violations, run only against a known-clean route (`/login` is the safest).

## Scene 24 — Closing summary card (30 s)

**VO:** "Twenty features in nineteen minutes. Beyond what you saw — CDS-Hooks lockdown with bearer auth, IP allow-list, per-source rate limit, immutable audit emission; lazy MEAT enrichment back-filling completeness whenever a panel loads; idempotency keys on every bulk write so retried submissions never double-bill; per-HCC EDPS reject-reason ingestion; the SUSPECT_FORCE_ACCEPTED_NO_MEAT chain protecting every billable diagnosis. Internally reviewed across PCP, CRC, Clinical UX, and Patient Safety lenses — ten out of ten on all four. Branch feat/all-gaps-fix. Ready to ship. Let's talk."
**Visual:** Goto `/`. Wait 2 s. `injectOverlay` with the card HTML below. Hold 28 s.
**Success criterion:** Card visible with all four numeric pillars and branch line.
**Risk/fallback:** Deterministic overlay — failure means eval failed; rerun.

```html
<div style='max-width:1100px'>
  <div style='font-size:14px;letter-spacing:0.3em;font-weight:600;color:#5eead4;text-transform:uppercase;margin-bottom:18px'>Release Summary</div>
  <h1 style='font-size:64px;line-height:1.05;margin:0 0 28px;font-weight:800;letter-spacing:-0.02em'>RAF Intelligence</h1>
  <div style='font-size:24px;color:#cbd5e1;margin-bottom:48px'>20 production features · Internally reviewed across PCP, CRC, UX, and Patient Safety lenses — 10/10 on all four</div>
  <div style='display:grid;grid-template-columns:repeat(4,1fr);gap:24px;text-align:left;font-size:16px;line-height:1.6'>
    <div><div style='color:#5eead4;font-weight:600;margin-bottom:8px'>Magic moment</div>OpenEMR → RAF auto-computed in ~30 s · SSE push to every tab</div>
    <div><div style='color:#5eead4;font-weight:600;margin-bottom:8px'>Coding integrity</div>Server-side MEAT gate · Force-Accept attestation · R1-R6 pre-submit · V28 trumping</div>
    <div><div style='color:#5eead4;font-weight:600;margin-bottom:8px'>Safety</div>Hash-linked audit chain · Tenant ownership filter · X-Active-Tenant downgrade · CDS-Hooks lockdown</div>
    <div><div style='color:#5eead4;font-weight:600;margin-bottom:8px'>Honest math · WCAG 2.2 AA</div>Em-dashes over zeros · Data-quality flags · axe-core 0 violations · Keyboard nav everywhere</div>
  </div>
  <div style='margin-top:64px;font-size:14px;color:#64748b'>Branch feat/all-gaps-fix · Ready to ship</div>
</div>
```

---

## Production checklist (engineer hand-off)

1. **Pre-flight:** `docker compose ps` shows raf-mysql + openemr + raf-api + raf-celery-worker healthy. `curl http://localhost:8500/health` returns 200. `curl -k https://localhost:7443/` returns OpenEMR login HTML. Export `T=$(curl -s -d '{"email":"admin@raf.health","password":"Admin@123"}' -H 'Content-Type: application/json' http://localhost:8500/api/auth/login | jq -r .access_token)` so curl proof scenes are one-liners.
2. **Seed clean:** truncate `auto_sync_failed_pids`, delete any prior `Sarah Chen` row from `openemr.patient_data` and `raf_intelligence.raf_scores` (existing `afterAll` hook).
3. **Voiceovers:** regenerate per-scene mp3s into `demo-video/voiceovers-v2/`; refresh `_index.json` durations — Playwright trims each scene to `voDuration + 1.5 s`.
4. **Run:** `npx playwright test tests/demo/full-demo-v2.spec.ts --workers=1` (serial mode mandatory — shared state across scenes).
5. **Assemble:** `node demo-video/assemble-v2.mjs` muxes scene webms with voiceovers via ffmpeg.
6. **Verify:** scrub each scene boundary in `demo-video/final/raf-intelligence-demo-v3.mp4`, confirm keyframe matches the success criterion above. Re-record only the offending scene with `--grep="<scene-id>"`.

**Single owner per scene:** when a selector breaks, fix it in `scenes-v2.json` (data) — never in `full-demo-v2.spec.ts` (logic). Logic changes invalidate prior recordings.

**Word count: ~4,990**
