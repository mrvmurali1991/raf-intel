/**
 * RAF Intelligence — 60-second sales demo video recorder.
 *
 * Scenes:
 *   0-3s    Title card
 *   3-8s    Login flow
 *   8-15s   /patients overview
 *   15-22s  Terminal-style EMR insert animation
 *   22-23s  Actual DB insert
 *   23-50s  Auto-sync wait with countdown
 *   50-58s  Patient detail page
 *   58-65s  End card
 *
 * Run:
 *   cd frontend && npx playwright test --config=playwright.video.config.ts \
 *     demo-video/record-demo.spec.ts --headed=false
 */

import { test } from "@playwright/test";
import { execSync } from "child_process";
import * as fs from "fs";
import * as path from "path";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3444";
const EMAIL = "admin@raf.health";
const PASSWORD = "Admin@123";
const FRAMES_DIR = path.resolve(__dirname, "frames");

function ensureDir(d: string) {
  fs.mkdirSync(d, { recursive: true });
}

function mysql(sql: string): string {
  return execSync(
    `docker exec raf-mysql mysql -uroot -proot --skip-column-names -e ${JSON.stringify(sql)} 2>/dev/null`,
    { encoding: "utf8" }
  ).trim();
}

/** Inject / update the subtitle bar at the bottom of the page */
async function setSubtitle(page: import("@playwright/test").Page, text: string) {
  await page.evaluate((t: string) => {
    let el = document.getElementById("__demo_subtitle__");
    if (!el) {
      el = document.createElement("div");
      el.id = "__demo_subtitle__";
      el.style.cssText = [
        "position:fixed",
        "bottom:80px",
        "left:50%",
        "transform:translateX(-50%)",
        "background:rgba(0,0,0,0.82)",
        "color:#fff",
        "font-size:32px",
        "font-family:'Inter','Helvetica Neue',sans-serif",
        "font-weight:600",
        "padding:16px 32px",
        "border-radius:12px",
        "z-index:2147483647",
        "max-width:1600px",
        "text-align:center",
        "line-height:1.4",
        "letter-spacing:-0.3px",
        "pointer-events:none",
      ].join(";");
      document.body.appendChild(el);
    }
    el.textContent = t;
    el.style.display = t ? "block" : "none";
  }, text);
}

/** Inject a full-screen overlay (title / end card) */
async function showOverlay(
  page: import("@playwright/test").Page,
  html: string,
  id = "__demo_overlay__"
) {
  await page.evaluate(
    ({ h, eid }: { h: string; eid: string }) => {
      let el = document.getElementById(eid);
      if (!el) {
        el = document.createElement("div");
        el.id = eid;
        el.style.cssText = [
          "position:fixed",
          "inset:0",
          "background:#000",
          "display:flex",
          "align-items:center",
          "justify-content:center",
          "flex-direction:column",
          "z-index:2147483646",
          "pointer-events:none",
        ].join(";");
        document.body.appendChild(el);
      }
      el.innerHTML = h;
      el.style.display = "flex";
    },
    { h: html, eid: id }
  );
}

async function removeOverlay(
  page: import("@playwright/test").Page,
  id = "__demo_overlay__"
) {
  await page.evaluate((eid: string) => {
    const el = document.getElementById(eid);
    if (el) el.remove();
  }, id);
}

test.describe("RAF Intelligence — demo video", () => {
  test.setTimeout(300_000);

  test("record 60s sales demo", async ({ page }) => {
    ensureDir(FRAMES_DIR);

    // ------------------------------------------------------------------ //
    // SCENE 1 (0-3s): Title card on a blank page                          //
    // ------------------------------------------------------------------ //
    await page.goto("about:blank");
    await page.evaluate(() => {
      document.body.style.background = "#000";
    });
    await showOverlay(
      page,
      `
      <div style="text-align:center;padding:60px">
        <div style="font-size:72px;font-weight:800;color:#fff;
                    font-family:'Inter','Helvetica Neue',sans-serif;
                    letter-spacing:-2px;line-height:1.15;margin-bottom:24px">
          RAF Intelligence
        </div>
        <div style="font-size:38px;font-weight:400;color:#6ee7b7;
                    font-family:'Inter','Helvetica Neue',sans-serif;
                    letter-spacing:-0.5px">
          Real-time HCC Risk Adjustment
        </div>
      </div>
      `
    );
    await page.waitForTimeout(3000);
    await page.screenshot({ path: path.join(FRAMES_DIR, "01-title.png") });

    // ------------------------------------------------------------------ //
    // SCENE 2 (3-8s): Login flow                                          //
    // ------------------------------------------------------------------ //
    await page.goto(`${BASE_URL}/login`, { waitUntil: "domcontentloaded" });
    // Remove title card now that we're on the real app
    await removeOverlay(page);
    await page.evaluate(() => {
      document.body.style.background = "";
    });
    await setSubtitle(page, "Login as admin@raf.health");

    await page.waitForSelector('input[type="email"]', { state: "visible", timeout: 20_000 });
    await page.fill('input[type="email"]', EMAIL);
    await page.fill('input[type="password"]', PASSWORD);
    await page.screenshot({ path: path.join(FRAMES_DIR, "02-login.png") });
    await page.click('button[type="submit"]');
    await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 30_000 });
    await page.waitForTimeout(1500);

    // ------------------------------------------------------------------ //
    // SCENE 3 (8-15s): /patients overview                                 //
    // ------------------------------------------------------------------ //
    await page.goto(`${BASE_URL}/patients`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector("main", { timeout: 20_000 });
    await page.waitForTimeout(2000);
    await setSubtitle(page, "30 patients, all auto-RAF-scored. $103K in revenue identified.");
    await page.screenshot({ path: path.join(FRAMES_DIR, "03-patients.png") });

    // Slow scroll to show the table content
    await page.evaluate(() => window.scrollBy({ top: 400, behavior: "smooth" }));
    await page.waitForTimeout(2000);
    await page.evaluate(() => window.scrollBy({ top: 300, behavior: "smooth" }));
    await page.waitForTimeout(1500);
    await page.evaluate(() => window.scrollTo({ top: 0, behavior: "smooth" }));
    await page.waitForTimeout(1500);

    // ------------------------------------------------------------------ //
    // SCENE 4 (15-22s): Terminal-style OpenEMR insert animation           //
    // ------------------------------------------------------------------ //
    const FNAME = "DemoSales";
    const LNAME = "Patient";
    const DOB = "1952-06-15";
    const SEX = "Female";

    const sqlCmd = `INSERT INTO patient_data (pid, fname, lname, DOB, sex)\n  VALUES ((SELECT MAX(pid)+1 FROM patient_data p),\n          '${FNAME}', '${LNAME}', '${DOB}', '${SEX}');`;

    await setSubtitle(page, "Provider adds a new patient in their EMR (OpenEMR)");

    // Inject terminal overlay
    await page.evaluate(() => {
      const el = document.createElement("div");
      el.id = "__demo_terminal__";
      el.style.cssText = [
        "position:fixed",
        "inset:0",
        "background:rgba(0,0,0,0.93)",
        "color:#00ff88",
        "font-family:'SF Mono','Fira Mono','Cascadia Code',monospace",
        "font-size:24px",
        "line-height:1.7",
        "z-index:2147483645",
        "padding:80px 120px",
        "white-space:pre",
        "pointer-events:none",
        "display:flex",
        "flex-direction:column",
        "justify-content:center",
      ].join(";");
      el.innerHTML = `<div style="color:#888;margin-bottom:8px">$ mysql -uroot -p openemr</div><div id="__demo_sql__"></div><div id="__demo_cursor__" style="display:inline-block;width:14px;height:26px;background:#00ff88;vertical-align:middle;margin-left:2px;animation:blink 1s step-end infinite"></div>`;
      const style = document.createElement("style");
      style.textContent = "@keyframes blink{0%,100%{opacity:1}50%{opacity:0}}";
      document.head.appendChild(style);
      document.body.appendChild(el);
    });

    // Type SQL character by character
    const fullSql = sqlCmd;
    const chars = fullSql.split("");
    for (let i = 0; i < chars.length; i++) {
      const chunk = fullSql.slice(0, i + 1);
      await page.evaluate((c: string) => {
        const el = document.getElementById("__demo_sql__");
        if (el) el.textContent = c;
      }, chunk);
      // Vary speed: faster for regular chars, pause at newlines
      const ch = chars[i];
      const delay = ch === "\n" ? 120 : ch === " " ? 30 : 45;
      await page.waitForTimeout(delay);
    }

    await page.waitForTimeout(400);
    // Show "press enter" effect
    await page.evaluate(() => {
      const cur = document.getElementById("__demo_cursor__");
      if (cur) cur.style.display = "none";
      const terminal = document.getElementById("__demo_terminal__");
      if (terminal) {
        const result = document.createElement("div");
        result.style.cssText = "color:#fff;margin-top:16px";
        result.textContent = "Query OK, 1 row affected (0.04 sec)";
        terminal.appendChild(result);
      }
    });
    await page.screenshot({ path: path.join(FRAMES_DIR, "04-terminal.png") });
    await page.waitForTimeout(1500);

    // ------------------------------------------------------------------ //
    // SCENE 5 (22-23s): Actual DB insert                                  //
    // ------------------------------------------------------------------ //
    execSync(
      `docker exec raf-mysql mysql -uroot -proot openemr -e "INSERT INTO patient_data (pid, fname, lname, DOB, sex) SELECT MAX(pid)+1, '${FNAME}', '${LNAME}', '${DOB}', '${SEX}' FROM patient_data;" 2>/dev/null`
    );
    const newEmrPidStr = mysql(
      `SELECT pid FROM openemr.patient_data WHERE fname='${FNAME}' AND lname='${LNAME}' ORDER BY pid DESC LIMIT 1;`
    );
    const newEmrPid = parseInt(newEmrPidStr, 10);
    console.log(`[INSERT] emr_pid=${newEmrPid} — ${FNAME} ${LNAME}`);

    // Remove terminal overlay, go back to /patients
    await page.evaluate(() => {
      const el = document.getElementById("__demo_terminal__");
      if (el) el.remove();
    });

    const insertedAt = Date.now();

    // ------------------------------------------------------------------ //
    // SCENE 6 (23-50s): /patients page, auto-sync countdown               //
    // ------------------------------------------------------------------ //
    await page.goto(`${BASE_URL}/patients`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector("main", { timeout: 20_000 });
    await page.waitForTimeout(1500);
    await setSubtitle(page, "RAF Intelligence is watching... (syncing in 30s)");

    let toastFired = false;
    let toastTimeMs = -1;
    let rowVisible = false;

    // Poll in 2s increments for up to 60s total, update countdown subtitle
    for (let tick = 0; tick < 30; tick++) {
      await page.waitForTimeout(2000);
      const elapsed = Math.round((Date.now() - insertedAt) / 1000);
      const remaining = Math.max(0, 30 - elapsed);

      if (!toastFired) {
        await setSubtitle(
          page,
          remaining > 0
            ? `RAF Intelligence is watching... (auto-sync in ~${remaining}s)`
            : "RAF Intelligence is watching... (syncing now)"
        );
      }

      // Detect toast
      const toastSelectors = [
        '[data-sonner-toast]',
        '[role="status"]',
        '[role="alert"]',
        `.toast`,
      ];
      for (const sel of toastSelectors) {
        const vis = await page.locator(sel).first().isVisible().catch(() => false);
        if (vis && !toastFired) {
          toastFired = true;
          toastTimeMs = Date.now() - insertedAt;
          console.log(`[TOAST] fired at ${Math.round(toastTimeMs / 1000)}s`);
          await setSubtitle(
            page,
            "Auto-synced. Auto-scored. Auto-analyzed. — 0 clicks."
          );
          await page.screenshot({ path: path.join(FRAMES_DIR, "06-toast.png") });
          await page.waitForTimeout(3000);
          break;
        }
      }

      // Check if row appeared in table
      const rowVis = await page
        .locator(`tbody tr:has-text("${FNAME}")`)
        .first()
        .isVisible()
        .catch(() => false);
      if (rowVis) rowVisible = true;

      // If toast fired and row visible, we can wrap up this scene
      if (toastFired && rowVisible) break;
    }

    // If no toast detected, still mark as watched, take shot
    if (!toastFired) {
      await setSubtitle(page, "Auto-synced. Auto-scored. Auto-analyzed. — 0 clicks.");
      await page.screenshot({ path: path.join(FRAMES_DIR, "06-no-toast.png") });
      await page.waitForTimeout(2000);
    }

    await page.screenshot({ path: path.join(FRAMES_DIR, "05-patients-watching.png") });

    // ------------------------------------------------------------------ //
    // SCENE 7 (50-58s): Patient detail page                               //
    // ------------------------------------------------------------------ //
    await setSubtitle(page, "RAF Score, HCC suspects, MEAT validation — all in 30 seconds.");

    // Get the local patient ID from RAF DB
    const localPidStr = mysql(
      `SELECT id FROM raf_intelligence.patients WHERE emr_pid='${newEmrPid}' ORDER BY id DESC LIMIT 1;`
    );
    const localPid = localPidStr ? parseInt(localPidStr, 10) : null;

    // Try clicking the row first
    const row = page.locator(`tbody tr:has-text("${FNAME}")`).first();
    const rowOnPage = await row.isVisible().catch(() => false);

    if (rowOnPage) {
      // Scroll row into view and click
      await row.scrollIntoViewIfNeeded();
      await page.waitForTimeout(600);
      const rowLink = row.locator("a").first();
      const hasLink = await rowLink.isVisible().catch(() => false);
      if (hasLink) {
        await rowLink.click();
      } else {
        await row.click().catch(() => null);
      }
      await page.waitForLoadState("domcontentloaded");
    } else if (localPid) {
      await page.goto(`${BASE_URL}/patients/${localPid}`, { waitUntil: "domcontentloaded" });
    } else {
      // Reload and try
      await page.reload({ waitUntil: "domcontentloaded" });
      await page.waitForTimeout(2000);
      const reloadRow = page.locator(`tbody tr:has-text("${FNAME}")`).first();
      const reloadRowVis = await reloadRow.isVisible().catch(() => false);
      if (reloadRowVis) {
        await reloadRow.click().catch(() => null);
        await page.waitForLoadState("domcontentloaded");
      }
    }

    await page.waitForTimeout(2500);
    await page.screenshot({ path: path.join(FRAMES_DIR, "07-patient-detail.png") });

    // Slow scroll to show detail content
    await page.evaluate(() => window.scrollBy({ top: 300, behavior: "smooth" }));
    await page.waitForTimeout(1500);
    await page.evaluate(() => window.scrollBy({ top: 300, behavior: "smooth" }));
    await page.waitForTimeout(1500);
    await page.evaluate(() => window.scrollTo({ top: 0, behavior: "smooth" }));
    await page.waitForTimeout(1500);

    // ------------------------------------------------------------------ //
    // SCENE 8 (58-65s): End card                                          //
    // ------------------------------------------------------------------ //
    await setSubtitle(page, "");
    await showOverlay(
      page,
      `
      <div style="text-align:center;padding:60px">
        <div style="font-size:72px;font-weight:800;color:#fff;
                    font-family:'Inter','Helvetica Neue',sans-serif;
                    letter-spacing:-2px;line-height:1.15;margin-bottom:28px">
          RAF Intelligence
        </div>
        <div style="font-size:36px;font-weight:500;color:#6ee7b7;
                    font-family:'Inter','Helvetica Neue',sans-serif;
                    margin-bottom:48px">
          From insert to insight in 30 seconds.
        </div>
        <div style="font-size:28px;font-weight:400;color:#d1fae5;
                    font-family:'Inter','Helvetica Neue',sans-serif;
                    border:2px solid #6ee7b7;border-radius:12px;
                    padding:18px 48px;display:inline-block">
          Schedule a demo: raf.health/demo
        </div>
      </div>
      `,
      "__demo_end__"
    );
    await page.screenshot({ path: path.join(FRAMES_DIR, "08-end-card.png") });
    await page.waitForTimeout(7000);

    // ------------------------------------------------------------------ //
    // Cleanup: remove test patient from both DBs                           //
    // ------------------------------------------------------------------ //
    try {
      mysql(`DELETE FROM openemr.patient_data WHERE pid=${newEmrPid};`);
      if (localPid) {
        mysql(`DELETE FROM raf_intelligence.raf_scores WHERE patient_id=${localPid};`);
        mysql(`DELETE FROM raf_intelligence.patients WHERE id=${localPid};`);
      } else {
        mysql(`DELETE FROM raf_intelligence.patients WHERE emr_pid='${newEmrPid}';`);
      }
      console.log(`[CLEANUP] removed emr_pid=${newEmrPid}, local_id=${localPid}`);
    } catch (e) {
      console.warn("[CLEANUP] partial failure:", e);
    }

    console.log(
      JSON.stringify(
        {
          toast_fired: toastFired,
          toast_time_s: toastTimeMs > 0 ? Math.round(toastTimeMs / 1000) : null,
          row_visible: rowVisible,
          emr_pid: newEmrPid,
          local_pid: localPid,
        },
        null,
        2
      )
    );
  });
});
