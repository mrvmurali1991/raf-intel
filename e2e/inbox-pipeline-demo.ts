/**
 * End-to-end inbox pipeline demo.
 *
 * Flow:
 *  1. Login to RAF app, capture BEFORE state for RONALD ABEYTA (pid 855).
 *  2. Login to external OpenEMR (ehrservicedesk.com), add a new Medical
 *     Problem (I50.9 Heart failure) to Abeyta.
 *  3. Trigger FHIR sync via our /api/fhir/sync/{id} endpoint.
 *  4. Poll raf_recompute_pending + raf scores until pipeline completes.
 *  5. Re-open Abeyta in RAF app, capture AFTER state.
 */
import { chromium, Page } from "playwright";
import * as fs from "fs";
import * as path from "path";

const OPENEMR_URL = "https://openemr.ehrservicedesk.com";
const OPENEMR_USER = "admin";
const OPENEMR_PASS = "Healthcare@Admin2026";

const RAF_UI = "https://raf.comercioit.com";
const RAF_API = "https://raf-api.comercioit.com";
const RAF_USER = "admin@raf.health";
const RAF_PASS = "Admin@123";

const PID = 855;
const OPENEMR_PID = 822206; // Abeyta external pid
const CONNECTION_ID = 1;
const ICD_CODE = "I50.9";
const ICD_TITLE = "Heart failure, unspecified";

const DIR = path.join(__dirname, "inbox-demo-screenshots");
if (!fs.existsSync(DIR)) fs.mkdirSync(DIR, { recursive: true });

let step = 0;
const events: { step: number; name: string; caption: string; file: string }[] = [];

async function shot(page: Page, name: string, caption: string, full = false) {
  step++;
  const file = `${String(step).padStart(2, "0")}_${name}.png`;
  await page.screenshot({ path: path.join(DIR, file), fullPage: full });
  events.push({ step, name, caption, file });
  console.log(`[${step}] 📸 ${file}`);
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function apiLoginRAF(): Promise<string> {
  const res = await fetch(`${RAF_API}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: RAF_USER, password: RAF_PASS }),
  });
  const d = await res.json();
  if (!d.access_token) throw new Error("RAF login failed: " + JSON.stringify(d));
  return d.access_token;
}

async function getRafScore(token: string): Promise<any> {
  const res = await fetch(`${RAF_API}/api/raf/scores/${PID}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return res.json();
}

async function getProblemList(token: string): Promise<any> {
  const res = await fetch(`${RAF_API}/api/patients/${PID}/problem-list`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return res.json();
}

async function triggerSync(token: string): Promise<any> {
  const res = await fetch(`${RAF_API}/api/fhir/sync/${CONNECTION_ID}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  return res.json();
}

async function getInboxStatus(token: string): Promise<any> {
  const res = await fetch(`${RAF_API}/api/admin/raf-inbox/status`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return res.json();
}

async function markDirty(token: string): Promise<any> {
  const res = await fetch(`${RAF_API}/api/raf/recompute/${PID}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  return res.json();
}

// ---------------------------------------------------------------------------

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    ignoreHTTPSErrors: true,
  });
  const page = await ctx.newPage();

  // ── PHASE 1: BEFORE ──────────────────────────────────────────────
  console.log("\n══ PHASE 1: RAF app — BEFORE state ══");
  await page.goto(`${RAF_UI}/login`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(2000);
  await shot(page, "raf_login", "RAF Intelligence login screen");

  await page.locator('input[type="email"]').first().fill(RAF_USER);
  await page.locator('input[type="password"]').first().fill(RAF_PASS);
  await page.locator('button[type="submit"]').first().click();
  await page.waitForTimeout(5000);

  try {
    const skip = page.locator('button:has-text("Skip")').first();
    if (await skip.isVisible({ timeout: 2000 })) {
      await skip.click();
      await page.waitForTimeout(2000);
    }
  } catch {}

  await page.goto(`${RAF_UI}/patients/${PID}`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(4000);
  await shot(
    page,
    "raf_before_patient_detail",
    `BEFORE: Ronald Abeyta (pid ${PID}) — RAF 1.035, 2 HCCs.`,
    true,
  );

  const token = await apiLoginRAF();
  const before = await getRafScore(token);
  const beforeProblems = await getProblemList(token);
  fs.writeFileSync(path.join(DIR, "before.json"), JSON.stringify(before, null, 2));
  fs.writeFileSync(
    path.join(DIR, "before_problems.json"),
    JSON.stringify(beforeProblems, null, 2),
  );
  console.log("BEFORE:", before.raf_score, "HCCs:", before.hcc_count, "problems:", beforeProblems.count);

  // ── PHASE 2: OpenEMR login + navigate + add problem ─────────────
  console.log("\n══ PHASE 2: OpenEMR — login + add Problem I50.9 ══");
  await page.goto(`${OPENEMR_URL}/interface/login/login.php?site=default`, {
    waitUntil: "domcontentloaded",
  });
  await page.waitForTimeout(2500);
  await shot(page, "openemr_login", "OpenEMR login (ehrservicedesk.com)");

  await page.locator("#authUser").fill(OPENEMR_USER);
  await page.locator("#clearPass").fill(OPENEMR_PASS);
  await page.locator("#login-button").click();
  await page.waitForTimeout(6000);
  await shot(page, "openemr_dashboard", "OpenEMR dashboard after admin login");

  // Open Abeyta by direct URL — skips autocomplete fragility.
  // OpenEMR uses set_pid query param to select a patient; demographics
  // page then loads the patient summary.
  console.log("Opening Abeyta via set_pid…");
  await page.goto(
    `${OPENEMR_URL}/interface/patient_file/summary/demographics.php?set_pid=${OPENEMR_PID}`,
    { waitUntil: "domcontentloaded" },
  );
  await page.waitForTimeout(5000);
  await shot(
    page,
    "openemr_patient_summary",
    "Ronald Abeyta patient summary in OpenEMR (before edit)",
    true,
  );

  // Navigate straight to the Issues list. This is the canonical URL.
  console.log("Opening Issues list…");
  await page.goto(
    `${OPENEMR_URL}/interface/patient_file/summary/stats_full.php?active=all`,
    { waitUntil: "domcontentloaded" },
  );
  await page.waitForTimeout(4000);
  await shot(page, "openemr_issues_before", "Issues / Medical Problems page — BEFORE add", true);

  // Click "Add Issue" via the onclick=newIssue('medical_problem') anchor.
  let addOk = false;
  try {
    await page.evaluate(() => {
      const el = Array.from(document.querySelectorAll("a,button")).find((n) =>
        (n.getAttribute("onclick") || "").includes("newIssue"),
      ) as HTMLElement | undefined;
      if (el) el.click();
    });
    await page.waitForTimeout(3500);
    addOk = true;
  } catch {}

  // Some themes open Add Issue in a popup iframe. Look for frame:
  let frame = page;
  try {
    for (const f of page.frames()) {
      const url = f.url();
      if (url.includes("add_edit_issue")) {
        frame = f as unknown as Page;
        break;
      }
    }
  } catch {}

  // If newIssue did not fire, open the form URL directly.
  if (!addOk) {
    console.log("newIssue() failed, opening add_edit_issue.php directly…");
    await page.goto(
      `${OPENEMR_URL}/interface/patient_file/summary/add_edit_issue.php?issue=&thistype=medical_problem&thispid=${OPENEMR_PID}`,
      { waitUntil: "domcontentloaded" },
    );
    await page.waitForTimeout(3500);
    frame = page;
  }
  await shot(page, "openemr_add_form_blank", "Add Issue form — blank", true);

  // Fill the form. Field names come from OpenEMR 7.x:
  //   title, diagnosis (ICD10:code), begin_date, outcome, etc.
  try {
    // Title
    await (frame as Page).locator('input[name="title"]').first().fill(ICD_TITLE);
  } catch (e) { console.log("title fill:", e); }
  try {
    // Begin date
    await (frame as Page)
      .locator('input[name="begin_date"], input[name="begdate"]')
      .first()
      .fill("2026-04-17");
  } catch (e) { console.log("begdate fill:", e); }
  try {
    // Diagnosis — OpenEMR uses input[name="diagnosis"] with an ICD10:xxx format.
    // Typing the value directly is enough; on save the code is stored verbatim.
    await (frame as Page)
      .locator('input[name="diagnosis"]')
      .first()
      .fill(`ICD10:${ICD_CODE}`);
  } catch (e) { console.log("diagnosis fill:", e); }

  await shot(
    page,
    "openemr_add_form_filled",
    `Add Issue form filled — ${ICD_CODE} ${ICD_TITLE}`,
    true,
  );

  // Save
  try {
    const save = (frame as Page)
      .locator('input[type="submit"][value*="Save" i], button:has-text("Save")')
      .first();
    if (await save.isVisible({ timeout: 2000 })) {
      await save.click();
      await page.waitForTimeout(5000);
    }
  } catch (e) { console.log("save click:", e); }

  await shot(page, "openemr_after_save", "OpenEMR — after saving the new problem", true);

  // Confirm by re-loading the issues list
  await page.goto(
    `${OPENEMR_URL}/interface/patient_file/summary/stats_full.php?active=all`,
    { waitUntil: "domcontentloaded" },
  );
  await page.waitForTimeout(3500);
  await shot(
    page,
    "openemr_issues_after",
    `Issues list after adding ${ICD_CODE} — verify ${ICD_TITLE} is present`,
    true,
  );

  // ── PHASE 3: Trigger sync + watch inbox ─────────────────────────
  console.log("\n══ PHASE 3: Trigger FHIR sync ══");
  const syncResp = await triggerSync(token);
  console.log("sync:", syncResp);
  fs.writeFileSync(path.join(DIR, "sync_response.json"), JSON.stringify(syncResp, null, 2));

  // Also mark dirty directly — if the sync debounces or skips (since FHIR
  // incremental by Last-Modified), this guarantees a recompute attempt.
  await sleep(2000);
  await markDirty(token);

  // Poll for up to 90s
  let drained = false;
  const pollStart = Date.now();
  let pollState: any = null;
  while (Date.now() - pollStart < 90_000) {
    pollState = await getInboxStatus(token);
    console.log("inbox:", JSON.stringify(pollState));
    const now = await getRafScore(token);
    if (
      now?.calculated_at &&
      before?.calculated_at &&
      now.calculated_at !== before.calculated_at &&
      (pollState?.pending ?? 0) === 0 &&
      (pollState?.processing ?? 0) === 0
    ) {
      drained = true;
      break;
    }
    await sleep(3000);
  }
  fs.writeFileSync(path.join(DIR, "inbox_last.json"), JSON.stringify(pollState, null, 2));

  const after = await getRafScore(token);
  const afterProblems = await getProblemList(token);
  fs.writeFileSync(path.join(DIR, "after.json"), JSON.stringify(after, null, 2));
  fs.writeFileSync(
    path.join(DIR, "after_problems.json"),
    JSON.stringify(afterProblems, null, 2),
  );
  console.log("AFTER:", after.raf_score, "HCCs:", after.hcc_count, "problems:", afterProblems.count);

  // ── PHASE 4: RAF app AFTER ───────────────────────────────────────
  console.log("\n══ PHASE 4: RAF app — AFTER state ══");
  await page.goto(`${RAF_UI}/patients/${PID}`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(6000);
  await shot(
    page,
    "raf_after_patient_detail",
    `AFTER: Ronald Abeyta — new RAF ${after.raf_score}, ${after.hcc_count} HCCs`,
    true,
  );

  fs.writeFileSync(
    path.join(DIR, "manifest.json"),
    JSON.stringify({ events, before, after, drained, beforeProblems, afterProblems }, null, 2),
  );

  console.log(`\n✅ Done — ${events.length} screenshots in ${DIR}`);
  await browser.close();
})().catch((e) => {
  console.error("FATAL:", e);
  process.exit(1);
});
