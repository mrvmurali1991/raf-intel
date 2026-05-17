/**
 * RAF Intelligence — full sales demo recorder v2.
 *
 * Adds the OpenEMR auto-sync magic moment as scenes 02/03/04, plus the
 * full 20-feature tour. Each scene records to a per-scene webm whose
 * length is later trimmed in ffmpeg to exactly match its voiceover.
 *
 *   tests/demo/full-demo-v2.spec.ts
 *   demo-video/scenes-v2.json           — script + per-scene actions
 *   demo-video/voiceovers/<id>.mp3      — Murf voiceover per scene
 *   demo-video/scenes/<id>.webm         — Playwright recording per scene
 */
import { test, type Page } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";
import { execSync } from "child_process";

const ROOT = path.resolve(__dirname, "../../../demo-video");
const SCENES = JSON.parse(fs.readFileSync(path.join(ROOT, "scenes-v2.json"), "utf8")) as Scene[];
const VOICE_INDEX = JSON.parse(
  fs.readFileSync(path.join(ROOT, "voiceovers-v2/_index.json"), "utf8")
) as { scenes: Record<string, number> };

const SCENE_DIR = path.join(ROOT, "scenes-v2");
fs.mkdirSync(SCENE_DIR, { recursive: true });

interface Action {
  type:
    | "wait"
    | "fill"
    | "click"
    | "clickAll"
    | "scroll"
    | "scrollIntoView"
    | "waitForUrl"
    | "hover"
    | "evalRunSql"
    | "injectOverlay"
    | "injectToast"
    | "reload"
    | "driveSlider"
    | "longHover"
    | "injectTooltipAt"
    | "captureNewPid"
    | "navigate"
    | "runTerminalCmd"
    | "consoleEval"
    | "pollUntilDbRow"
    | "openDevtoolsNetworkPanel"
    | "selectOption";
  ms?: number;
  selector?: string;
  value?: string;
  to?: number;
  url?: string;
  label?: string;
  /** For clickAll: max items to click */
  count?: number;
  /** For injectOverlay: HTML body of the overlay */
  html?: string;
  /** For runTerminalCmd: shell command to run and display */
  cmd?: string;
  /** For consoleEval: JS source to evaluate in page context */
  js?: string;
  /** For pollUntilDbRow: SQL that should return >=1 row when condition met */
  sql?: string;
  /** For pollUntilDbRow: max wait in ms before giving up */
  timeoutMs?: number;
  /** For pollUntilDbRow: docker mysql database name */
  database?: string;
  /** Hold overlay on-screen for this many ms (runTerminalCmd / consoleEval / openDevtoolsNetworkPanel) */
  holdMs?: number;
  /** For openDevtoolsNetworkPanel: header name to highlight in entries */
  header?: string;
}

interface Scene {
  id: string;
  title: string;
  voiceover: string;
  url: string;
  actions: Action[];
  /** DOM selector that must be visible before scrolling/recording starts.
   *  Without this every scene races the SPA's initial fetch and we
   *  freeze on the loading spinner. Default falls through to body text. */
  readyFor?: string;
  /** Optional readyForText — useful when there's no stable test-id. */
  readyForText?: string;
  /** Skip RAF Intelligence auth injection — for cross-origin scenes
   *  like the OpenEMR EMR shown for the magic moment setup. */
  noAuth?: boolean;
  /** Accept self-signed certificates — needed for OpenEMR HTTPS. */
  acceptHttps?: boolean;
}

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3444";
const EMAIL = "admin@raf.health";
const PASSWORD = "Admin@123";

// State shared across scenes for the OpenEMR magic moment.
const sharedState: {
  newPid: number | null;
  newFname: string;
} = { newPid: null, newFname: "" };

function dockerMysql(sql: string, database = "openemr"): string {
  return execSync(
    `docker exec raf-mysql mysql -uroot -proot ${database} -e ${JSON.stringify(sql)} 2>/dev/null`,
    { encoding: "utf8", timeout: 15_000 }
  );
}

function getNextPid(): number {
  const out = dockerMysql("SELECT COALESCE(MAX(pid),0)+1 AS next_pid FROM patient_data;");
  const match = out.match(/(\d+)\s*$/m);
  if (!match) throw new Error(`Could not parse next pid from: ${out}`);
  return parseInt(match[1], 10);
}

function insertOpenemrPatient(pid: number, fname: string): void {
  // pubpid is the patient's MRN — set it to a clean Acme-style MRN so
  // the demo doesn't expose a test-data Date.now() suffix.
  const pubpid = `AH${String(pid).padStart(6, "0")}`;
  dockerMysql(
    `INSERT INTO patient_data (pid, pubpid, fname, lname, DOB, sex, providerID) ` +
    `VALUES (${pid}, '${pubpid}', '${fname}', 'Chen', '1953-08-14', 'Female', 1);`
  );
}

function cleanupOpenemrPatient(pid: number, fname: string): void {
  try {
    dockerMysql(`DELETE FROM patient_data WHERE pid=${pid} AND lname='Chen';`);
  } catch { /* ignore */ }
  try {
    dockerMysql(
      `DELETE FROM raf_scores WHERE patient_id=${pid};`,
      "raf_intelligence"
    );
  } catch { /* ignore */ }
  try {
    dockerMysql(
      `DELETE FROM auto_sync_failed_pids WHERE emr_pid=${pid};`,
      "raf_intelligence"
    );
  } catch { /* ignore */ }
}

async function runActions(page: Page, actions: Action[]) {
  for (const a of actions) {
    try {
      switch (a.type) {
        case "wait":
          await page.waitForTimeout(a.ms ?? 500);
          break;
        case "fill":
          if (a.selector && a.value !== undefined) {
            await page.locator(a.selector).first().fill(a.value, { timeout: 8000 });
          }
          break;
        case "click":
          if (a.selector) {
            await page.locator(a.selector).first().click({ timeout: 8000 });
          }
          break;
        case "hover":
          if (a.selector) {
            await page.locator(a.selector).first().hover({ timeout: 8000 });
          }
          break;
        case "scroll":
          await page.evaluate((y) => window.scrollTo({ top: y, behavior: "smooth" }), a.to ?? 0);
          break;
        case "waitForUrl":
          if (a.url) {
            await page.waitForURL((u) => u.pathname === a.url || u.pathname.startsWith(a.url!), {
              timeout: 15000,
            });
          }
          break;
        case "clickAll":
          if (a.selector) {
            // Some checkboxes are intentionally faded until hover for a
            // clean worklist; force-visible them so .check() doesn't time
            // out on visibility, then click.
            await page.addStyleTag({
              content: `${a.selector} { opacity: 1 !important; visibility: visible !important; }`,
            });
            const all = page.locator(a.selector);
            const total = Math.min(await all.count(), a.count ?? 3);
            for (let i = 0; i < total; i++) {
              try {
                await all.nth(i).check({ timeout: 4000, force: true });
              } catch {
                try { await all.nth(i).click({ timeout: 3000, force: true }); } catch { /* skip */ }
              }
              await page.waitForTimeout(200);
            }
          }
          break;
        case "selectOption":
          if (a.selector && a.value !== undefined) {
            await page.locator(a.selector).first().selectOption(a.value, { timeout: 6000 });
          }
          break;
        case "scrollIntoView":
          if (a.selector) {
            await page.locator(a.selector).first().scrollIntoViewIfNeeded({ timeout: 6000 });
          }
          break;
        case "injectOverlay":
          if (a.html) {
            await page.evaluate((html: string) => {
              const wrap = document.createElement("div");
              wrap.id = "demo-overlay-card";
              wrap.style.cssText =
                "position:fixed;inset:0;display:flex;align-items:center;justify-content:center;" +
                "background:linear-gradient(135deg,#0f172a 0%,#134e4a 100%);z-index:100000;" +
                "color:#f8fafc;font-family:Inter,system-ui,sans-serif;padding:48px;text-align:center;";
              wrap.innerHTML = html;
              document.body.appendChild(wrap);
            }, a.html);
          }
          break;
        case "injectToast":
          // Render the same shape the SPA renders for an auto-sync toast,
          // so the demo guarantees a visible "magic moment" regardless of
          // SSE timing variance across 30s auto-sync cycles.
          await page.evaluate((label: string) => {
            const old = document.getElementById("demo-fake-toast");
            if (old) old.remove();
            const div = document.createElement("div");
            div.id = "demo-fake-toast";
            div.setAttribute("role", "status");
            div.setAttribute("aria-live", "polite");
            div.style.cssText =
              "position:fixed;top:20px;right:20px;z-index:99999;display:flex;align-items:center;" +
              "gap:10px;background-color:#0f172a;color:#f8fafc;padding:12px 16px;border-radius:10px;" +
              "box-shadow:0 8px 24px rgba(0,0,0,0.25);font-size:14px;font-weight:500;" +
              "font-family:Inter,system-ui,sans-serif;max-width:380px;";
            div.innerHTML =
              "<span style='font-size:18px;flex-shrink:0'>\u{1F195}</span>" +
              `<span style='flex:1'>${label}</span>` +
              "<span style='color:#94a3b8;display:flex'>✕</span>";
            document.body.appendChild(div);
          }, a.label || "New patient synced: SC (·0045) (RAF 0.40)");
          break;
        case "reload":
          await page.reload({ waitUntil: "domcontentloaded", timeout: 20000 });
          break;
        case "driveSlider":
          if (a.selector !== undefined && a.value !== undefined) {
            // Fire a real input event so React picks up the value. The
            // selector may use a magic suffix "#N" to mean "Nth match" —
            // useful when targeting one of multiple range inputs that
            // share a generated id.
            await page.evaluate(
              ({ sel, val }) => {
                let el: HTMLInputElement | null;
                const m = sel.match(/^(.*?)#(\d+)$/);
                if (m) {
                  const all = document.querySelectorAll(m[1]) as NodeListOf<HTMLInputElement>;
                  el = all[Number(m[2])] || null;
                } else {
                  el = document.querySelector(sel) as HTMLInputElement | null;
                }
                if (!el) return;
                const setter = Object.getOwnPropertyDescriptor(
                  window.HTMLInputElement.prototype,
                  "value"
                )?.set;
                setter?.call(el, String(val));
                el.dispatchEvent(new Event("input", { bubbles: true }));
                el.dispatchEvent(new Event("change", { bubbles: true }));
              },
              { sel: a.selector, val: Number(a.value) }
            );
          }
          break;
        case "injectTooltipAt":
          // Pin a tooltip at a fixed viewport coordinate so the keyframe
          // always captures it regardless of native hover timing or
          // selector flakiness on the disabled-Accept span.
          await page.evaluate(
            ({ label, top }) => {
              const old = document.getElementById("demo-tooltip-fixed");
              if (old) old.remove();
              // Find the first "Accept" text occurrence in the viewport
              // and anchor relative to it, falling back to (top, 580px).
              let x = 580;
              let y = top;
              const all = Array.from(document.querySelectorAll("button, span, [role=button]"));
              for (const el of all) {
                if ((el.textContent || "").trim() === "Accept") {
                  const r = (el as HTMLElement).getBoundingClientRect();
                  if (r.top > 100 && r.top < 700) {
                    x = Math.max(20, r.left - 50);
                    y = Math.max(20, r.top - 38);
                    break;
                  }
                }
              }
              const tip = document.createElement("div");
              tip.id = "demo-tooltip-fixed";
              tip.setAttribute("role", "tooltip");
              tip.style.cssText =
                `position:fixed;top:${y}px;left:${x}px;z-index:99999;` +
                "background:#0f172a;color:#f8fafc;padding:8px 12px;border-radius:6px;" +
                "font-size:12px;font-weight:500;font-family:Inter,system-ui,sans-serif;" +
                "box-shadow:0 6px 18px rgba(0,0,0,0.3);max-width:300px;line-height:1.4;" +
                "white-space:nowrap;";
              // Tip arrow
              tip.innerHTML =
                `${label}` +
                "<span style='position:absolute;bottom:-5px;left:60px;width:10px;height:10px;background:#0f172a;transform:rotate(45deg);'></span>";
              document.body.appendChild(tip);
            },
            { label: a.label || "Add MEAT evidence before accepting", top: a.to ?? 380 }
          );
          break;
        case "longHover":
          if (a.selector) {
            try {
              await page.locator(a.selector).first().hover({ timeout: 6000 });
              await page.waitForTimeout(a.ms ?? 1500);
              // Pin a guaranteed visible tooltip overlay above the hovered
              // element so the keyframe captures the constraint text even
              // when the native tooltip auto-dismisses or never fires.
              if (a.label) {
                await page.evaluate(
                  ({ sel, label }) => {
                    const target = document.querySelector(sel) as HTMLElement | null;
                    if (!target) return;
                    const old = document.getElementById("demo-tooltip");
                    if (old) old.remove();
                    const rect = target.getBoundingClientRect();
                    const tip = document.createElement("div");
                    tip.id = "demo-tooltip";
                    tip.setAttribute("role", "tooltip");
                    const top = Math.max(8, rect.top + window.scrollY - 38);
                    const left = Math.max(8, rect.left + window.scrollX - 80);
                    tip.style.cssText =
                      `position:absolute;top:${top}px;left:${left}px;z-index:99999;` +
                      "background:#0f172a;color:#f8fafc;padding:6px 10px;border-radius:6px;" +
                      "font-size:12px;font-weight:500;font-family:Inter,system-ui,sans-serif;" +
                      "box-shadow:0 4px 12px rgba(0,0,0,0.25);max-width:280px;line-height:1.35;" +
                      "white-space:nowrap;";
                    tip.textContent = label;
                    document.body.appendChild(tip);
                  },
                  { sel: a.selector, label: a.label }
                );
              }
            } catch { /* skip if not in viewport */ }
          }
          break;
        case "navigate":
          if (a.url) {
            try {
              await page.goto(a.url, { waitUntil: "domcontentloaded", timeout: 20000 });
            } catch (err) {
              console.log(`  ⚠️  navigate failed: ${(err as Error).message.slice(0, 120)}`);
            }
          }
          break;
        case "captureNewPid": {
          // After an OpenEMR UI insert, query the DB for the newest pid
          // matching our demo patient so subsequent scenes can deep-link.
          try {
            const out = dockerMysql(
              "SELECT pid FROM patient_data WHERE lname='Chen' ORDER BY pid DESC LIMIT 1;"
            );
            const m = out.match(/(\d+)\s*$/m);
            if (m) {
              sharedState.newPid = parseInt(m[1], 10);
              sharedState.newFname = "Sarah";
              console.log(`    ▸ captured newPid=${sharedState.newPid}`);
            }
          } catch (err) {
            console.log(`    ⚠️  captureNewPid failed: ${(err as Error).message.slice(0, 120)}`);
          }
          break;
        }
        case "evalRunSql": {
          // Fire the OpenEMR insert non-blocking so the recording keeps
          // rolling. The 30s auto-sync cycle will detect it within ~25s.
          if (a.label) console.log(`    ▸ ${a.label}`);
          const pid = getNextPid();
          const fname = "Sarah";
          sharedState.newPid = pid;
          sharedState.newFname = fname;
          insertOpenemrPatient(pid, fname);
          console.log(`    ▸ inserted pid=${pid} fname=${fname}`);
          break;
        }
        case "runTerminalCmd": {
          // Render a fake terminal panel with `$ <cmd>` + first ~12 lines
          // of stdout. Used for on-camera curl / proof shots.
          if (!a.cmd) break;
          let out = "";
          let isErr = false;
          try {
            out = execSync(a.cmd, { encoding: "utf8", timeout: 10_000 });
          } catch (err) {
            isErr = true;
            const e = err as { stderr?: Buffer | string; message?: string };
            out = (e.stderr ? e.stderr.toString() : e.message) || "(no output)";
          }
          const lines = out.split(/\r?\n/).slice(0, 12).join("\n");
          await page.evaluate(
            ({ cmd, body, title, err }) => {
              const old = document.getElementById("demo-terminal-overlay");
              if (old) old.remove();
              const wrap = document.createElement("div");
              wrap.id = "demo-terminal-overlay";
              wrap.style.cssText =
                "position:fixed;top:120px;right:20px;width:560px;z-index:99999;" +
                "background:#0b1120;color:#f8fafc;padding:16px;border-radius:8px;" +
                "box-shadow:0 12px 32px rgba(0,0,0,0.45);font-family:'SF Mono',Menlo,Consolas,monospace;" +
                "font-size:13px;line-height:1.5;white-space:pre-wrap;word-break:break-all;";
              const titleHtml = title
                ? `<div style='color:#94a3b8;font-size:11px;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:8px'>${title}</div>`
                : "";
              const promptColor = err ? "#f87171" : "#4ade80";
              wrap.innerHTML =
                titleHtml +
                `<div style='color:${promptColor}'>$ ${cmd}</div>` +
                `<div style='color:#f8fafc;margin-top:6px'>${body.replace(/</g, "&lt;")}</div>`;
              document.body.appendChild(wrap);
            },
            { cmd: a.cmd, body: lines, title: a.label || "", err: isErr }
          );
          await page.waitForTimeout(a.holdMs ?? 8000);
          break;
        }
        case "consoleEval": {
          // Run JS in page context and render the result console-style.
          if (!a.js) break;
          let result: unknown;
          let isErr = false;
          try {
            result = await page.evaluate(a.js);
          } catch (err) {
            isErr = true;
            result = (err as Error).message;
          }
          let rendered: string;
          try {
            rendered = JSON.stringify(result, null, 2) ?? String(result);
          } catch {
            rendered = String(result);
          }
          await page.evaluate(
            ({ js, body, title, err }) => {
              const old = document.getElementById("demo-console-overlay");
              if (old) old.remove();
              const wrap = document.createElement("div");
              wrap.id = "demo-console-overlay";
              wrap.style.cssText =
                "position:fixed;top:120px;left:20px;width:560px;max-height:520px;overflow:hidden;z-index:99999;" +
                "background:#0b1120;color:#f8fafc;padding:16px;border-radius:8px;" +
                "box-shadow:0 12px 32px rgba(0,0,0,0.45);font-family:'SF Mono',Menlo,Consolas,monospace;" +
                "font-size:13px;line-height:1.5;white-space:pre-wrap;word-break:break-all;";
              const titleHtml = title
                ? `<div style='color:#94a3b8;font-size:11px;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:8px'>${title}</div>`
                : "";
              const promptColor = err ? "#f87171" : "#60a5fa";
              wrap.innerHTML =
                titleHtml +
                `<div style='color:${promptColor}'>&gt; ${js.replace(/</g, "&lt;")}</div>` +
                `<div style='color:#f8fafc;margin-top:6px'>${body.replace(/</g, "&lt;")}</div>`;
              document.body.appendChild(wrap);
            },
            { js: a.js, body: rendered.slice(0, 2000), title: a.label || "", err: isErr }
          );
          await page.waitForTimeout(a.holdMs ?? 8000);
          break;
        }
        case "pollUntilDbRow": {
          // Block until SQL returns ≥1 row (used as a deterministic
          // keyframe gate for the magic-moment scene).
          if (!a.sql) break;
          const timeoutMs = a.timeoutMs ?? 60_000;
          const db = a.database ?? "raf_intelligence";
          const started = Date.now();
          let matched = false;
          while (Date.now() - started < timeoutMs) {
            try {
              const out = dockerMysql(a.sql, db);
              // dockerMysql with -e prints a header line plus one row per match.
              const lines = out.split(/\r?\n/).filter((l) => l.trim().length > 0);
              if (lines.length >= 2) {
                matched = true;
                break;
              }
            } catch { /* keep polling */ }
            await page.waitForTimeout(2000);
          }
          const elapsed = ((Date.now() - started) / 1000).toFixed(1);
          if (matched) {
            console.log(`    ✓ pollUntilDbRow matched after ${elapsed}s`);
          } else {
            console.log(`  ⚠️  pollUntilDbRow timed out after ${elapsed}s: ${a.sql.slice(0, 80)}`);
          }
          break;
        }
        case "openDevtoolsNetworkPanel": {
          // Visual-only DevTools Network panel — we can't open real
          // DevTools in headless Chromium, so render a styled overlay
          // pulling from performance.getEntriesByType('resource').
          await page.evaluate(
            ({ filter, header, title, holdMs }) => {
              const old = document.getElementById("demo-devtools-network");
              if (old) old.remove();
              type Entry = PerformanceResourceTiming & { responseStatus?: number };
              const all = (performance.getEntriesByType("resource") as Entry[])
                .filter((e) => (filter ? e.name.includes(filter) : true))
                .slice(-12)
                .reverse();
              const rows = all
                .map((e) => {
                  const u = (() => {
                    try { return new URL(e.name); } catch { return null; }
                  })();
                  const path = u ? (u.pathname + u.search).slice(0, 60) : e.name.slice(0, 60);
                  const status = e.responseStatus ?? 200;
                  const statusColor = status >= 400 ? "#f87171" : status >= 300 ? "#fbbf24" : "#4ade80";
                  const method = e.initiatorType === "fetch" || e.initiatorType === "xmlhttprequest"
                    ? "GET"
                    : e.initiatorType.toUpperCase();
                  return (
                    `<div style='display:grid;grid-template-columns:50px 1fr 60px;gap:8px;padding:4px 0;border-bottom:1px solid #1e293b'>` +
                      `<span style='color:#a78bfa'>${method}</span>` +
                      `<span style='color:#f8fafc;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'>${path.replace(/</g, "&lt;")}</span>` +
                      `<span style='color:${statusColor};text-align:right'>${status}</span>` +
                    `</div>`
                  );
                })
                .join("");
              const headerRow = header
                ? `<div style='margin-top:10px;padding:8px;background:#1e293b;border-radius:4px;color:#fbbf24;font-weight:500'>Request header: ${header}</div>`
                : "";
              const wrap = document.createElement("div");
              wrap.id = "demo-devtools-network";
              wrap.style.cssText =
                "position:fixed;bottom:20px;right:20px;width:540px;max-height:420px;overflow:auto;z-index:99999;" +
                "background:#0b1120;color:#f8fafc;padding:14px;border-radius:8px;" +
                "box-shadow:0 12px 32px rgba(0,0,0,0.45);font-family:'SF Mono',Menlo,Consolas,monospace;" +
                "font-size:12px;line-height:1.5;border:1px solid #1e293b;";
              wrap.innerHTML =
                `<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;padding-bottom:8px;border-bottom:1px solid #1e293b'>` +
                  `<span style='color:#f8fafc;font-weight:600'>Network</span>` +
                  `<span style='color:#94a3b8;font-size:11px'>${title || (filter ?? "all resources")}</span>` +
                `</div>` +
                (rows || `<div style='color:#94a3b8'>(no matching entries)</div>`) +
                headerRow;
              document.body.appendChild(wrap);
              // Auto-hold handled by Playwright waitForTimeout
              void holdMs;
            },
            { filter: a.url ?? "", header: a.header ?? "", title: a.label ?? "", holdMs: a.holdMs ?? 8000 }
          );
          await page.waitForTimeout(a.holdMs ?? 8000);
          break;
        }
      }
    } catch (err) {
      console.log(`  ⚠️  action ${a.type} failed: ${(err as Error).message.slice(0, 120)}`);
    }
  }
}

// Login via API and capture BOTH the access_token and the HttpOnly
// raf_refresh_token cookie — the latter is what the SPA actually uses
// on boot to bootstrap auth. Without it the frontend renders a stuck
// loading spinner forever.
async function apiLogin(): Promise<{ token: string; refresh: string }> {
  const apiUrl = process.env.API_URL ?? "http://localhost:8500";
  const r = await fetch(`${apiUrl}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: EMAIL, password: PASSWORD }),
  });
  if (!r.ok) throw new Error(`login ${r.status}: ${await r.text()}`);
  const j = (await r.json()) as { access_token: string };
  const setCookies = r.headers.get("set-cookie") || "";
  const m = setCookies.match(/raf_refresh_token=([^;]+)/);
  if (!m) throw new Error(`raf_refresh_token cookie not found in ${setCookies.slice(0, 200)}`);
  return { token: j.access_token, refresh: m[1] };
}

async function applyAuthToContext(
  ctx: import("@playwright/test").BrowserContext,
  creds: { token: string; refresh: string }
) {
  const u = new URL(BASE_URL);
  await ctx.addCookies([
    {
      name: "raf_refresh_token",
      value: creds.refresh,
      domain: u.hostname,
      path: "/",
      httpOnly: true,
      secure: false,
      sameSite: "Lax",
    },
    {
      name: "raf_authenticated",
      value: "true",
      domain: u.hostname,
      path: "/",
      httpOnly: false,
      secure: false,
      sameSite: "Lax",
    },
  ]);
  // Pre-seed an in-memory token via init script so the SPA doesn't even
  // need to wait for /api/auth/refresh on first render.
  await ctx.addInitScript((t: string) => {
    try {
      window.localStorage.setItem("access_token", t);
    } catch { /* SSR safe */ }
  }, creds.token);
}

test.describe.configure({ mode: "serial" });
test.describe("Full RAF Intelligence demo v2", () => {
  let cachedCreds: { token: string; refresh: string } | undefined;

  test.beforeAll(async () => {
    cachedCreds = await apiLogin();
    console.log(`  ✓ api-login token=${cachedCreds.token.slice(0, 12)}… refresh=${cachedCreds.refresh.slice(0, 12)}…`);
  });

  test.afterAll(async () => {
    if (sharedState.newPid !== null) {
      try {
        cleanupOpenemrPatient(sharedState.newPid, sharedState.newFname);
        console.log(`  ✓ cleanup: deleted demo pid=${sharedState.newPid}`);
      } catch (err) {
        console.log(`  ⚠️  cleanup failed: ${(err as Error).message}`);
      }
    }
  });

  for (const scene of SCENES) {
    test(scene.id, async ({ browser }) => {
      const voDuration = VOICE_INDEX.scenes[scene.id] ?? 30;
      const targetSec = Math.max(8, voDuration + 1.5);
      const start = Date.now();
      console.log(`\n▶ ${scene.id} (voiceover ${voDuration.toFixed(1)}s)`);

      const useAuth = scene.id !== "00-cold-open" && !scene.noAuth;
      const ctx = await browser.newContext({
        baseURL: BASE_URL,
        viewport: { width: 1440, height: 900 },
        recordVideo: { dir: SCENE_DIR, size: { width: 1440, height: 900 } },
        ignoreHTTPSErrors: !!scene.acceptHttps,
      });
      if (useAuth) {
        // Get fresh creds every scene — the cold-open scene's UI login
        // invalidates the cached session because the backend rotates
        // session_id on every login, leaving the cached refresh token
        // pointing at a revoked session. Fresh API login per scene is
        // ~50ms and guarantees the token is live.
        cachedCreds = await apiLogin();
        await applyAuthToContext(ctx, cachedCreds);
      }
      const page = await ctx.newPage();

      try {
        let targetUrl = scene.url;
        if (targetUrl === "EMR_SYNC_DETAIL") {
          targetUrl = sharedState.newPid !== null ? `/patients/${sharedState.newPid}` : "/patients";
        }
        // Absolute URLs (https://…) navigate to that host (used for the
        // OpenEMR EMR demo). Relative URLs resolve against baseURL.
        await page.goto(targetUrl, { waitUntil: "domcontentloaded", timeout: 30000 });
      } catch (err) {
        console.log(`  ⚠️  goto failed: ${(err as Error).message.slice(0, 120)}`);
      }

      // Hard wait for the page to actually render past the global loading
      // spinner. Two strategies: explicit selector OR text marker. If
      // neither resolves within 18s, log and continue (scene will still
      // run, but timing will be off). Without this every scene froze on
      // the loader and 20/21 scenes recorded blank in v2 round 1.
      try {
        if (scene.readyFor) {
          await page.waitForSelector(scene.readyFor, { state: "visible", timeout: 18000 });
        } else if (scene.readyForText) {
          await page.getByText(scene.readyForText, { exact: false }).first().waitFor({
            state: "visible",
            timeout: 18000,
          });
        } else {
          // Fallback: just wait until the loader spinner clears.
          await page.waitForFunction(
            () => {
              const text = document.body.innerText || "";
              return text.length > 500;
            },
            { timeout: 18000 }
          );
        }
      } catch (e) {
        console.log(`  ⚠️  readyFor wait timed out: ${(e as Error).message.slice(0, 120)}`);
      }
      await page.waitForTimeout(800);

      await runActions(page, scene.actions);

      // Hold the last frame until total elapsed >= voiceover + 1.5s tail.
      const elapsedSec = (Date.now() - start) / 1000;
      const remainingSec = targetSec - elapsedSec;
      if (remainingSec > 0) {
        await page.waitForTimeout(remainingSec * 1000);
      }

      const video = page.video();
      await ctx.close();
      if (video) {
        const rawPath = await video.path();
        const destPath = path.join(SCENE_DIR, `${scene.id}.webm`);
        try {
          fs.renameSync(rawPath, destPath);
          console.log(`  ✓ saved ${destPath} (${((Date.now() - start) / 1000).toFixed(1)}s elapsed)`);
        } catch (err) {
          fs.copyFileSync(rawPath, destPath);
          console.log(`  ✓ copied to ${destPath}`);
        }
      }
    });
  }
});
