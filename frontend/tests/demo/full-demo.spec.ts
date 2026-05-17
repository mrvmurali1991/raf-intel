/**
 * Full RAF Intelligence demo recorder.
 *
 * Reads /demo-video/scenes.json and /demo-video/voiceovers/_index.json,
 * records ONE webm video per scene whose duration matches the Murf
 * voiceover for that scene (plus a small tail buffer for grace).
 *
 * Output: /demo-video/scenes/<scene-id>.webm  (one per scene)
 */
import { test, type Page } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";

const ROOT = path.resolve(__dirname, "../../../demo-video");
const SCENES = JSON.parse(fs.readFileSync(path.join(ROOT, "scenes.json"), "utf8")) as Scene[];
const VOICE_INDEX = JSON.parse(
  fs.readFileSync(path.join(ROOT, "voiceovers", "_index.json"), "utf8")
) as { scenes: Record<string, number> };

const SCENE_DIR = path.join(ROOT, "scenes");
fs.mkdirSync(SCENE_DIR, { recursive: true });

interface Action {
  type: "wait" | "fill" | "click" | "scroll" | "waitForUrl" | "hover";
  ms?: number;
  selector?: string;
  value?: string;
  to?: number;
  url?: string;
}

interface Scene {
  id: string;
  title: string;
  voiceover: string;
  url: string;
  actions: Action[];
}

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3444";
const EMAIL = "admin@raf.health";
const PASSWORD = "Admin@123";

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
      }
    } catch (err) {
      console.log(`  ⚠️  action ${a.type} failed: ${(err as Error).message.slice(0, 120)}`);
    }
  }
}

async function loginIfNeeded(page: Page) {
  if (!page.url().includes("/login")) {
    // try API login + cookie
  }
}

// Process scenes sequentially so we can use a single browser session for
// post-login navigation. Scene 1 logs in via UI inside its actions; scenes
// 2+ assume the session cookie is still set.
test.describe.configure({ mode: "serial" });
test.describe("Full RAF Intelligence demo", () => {
  let sharedAuthState: string | undefined;

  test.beforeAll(async ({ browser }) => {
    // Log in once, save storage state for reuse across per-scene contexts.
    const ctx = await browser.newContext({ baseURL: BASE_URL });
    const page = await ctx.newPage();
    await page.goto("/login", { waitUntil: "domcontentloaded" });
    await page.locator('input[type=email], input[name=email]').first().fill(EMAIL);
    await page.locator('input[type=password], input[name=password]').first().fill(PASSWORD);
    await page.locator('button[type=submit]').first().click();
    try {
      await page.waitForURL((u) => !u.pathname.includes("/login"), { timeout: 15000 });
    } catch {
      console.log("  ⚠️  login navigation timeout — proceeding with cookies anyway");
    }
    sharedAuthState = path.join(ROOT, "scenes", ".auth-state.json");
    await ctx.storageState({ path: sharedAuthState });
    await ctx.close();
    console.log(`  ✓ logged in, auth state at ${sharedAuthState}`);
  });

  for (const scene of SCENES) {
    test(scene.id, async ({ browser }) => {
      const voDuration = VOICE_INDEX.scenes[scene.id] ?? 30;
      // Pad video to be voiceover duration + 1.5s tail, minimum 6s.
      const targetSec = Math.max(6, voDuration + 1.5);
      const start = Date.now();
      console.log(`\n▶ ${scene.id} (target ${targetSec.toFixed(1)}s, voiceover ${voDuration.toFixed(1)}s)`);

      // Scene 1 starts at /login (no auth); scenes 2+ use saved auth.
      const useAuth = scene.id !== "01-intro";
      const ctx = await browser.newContext({
        baseURL: BASE_URL,
        viewport: { width: 1440, height: 900 },
        recordVideo: { dir: SCENE_DIR, size: { width: 1440, height: 900 } },
        ...(useAuth && sharedAuthState ? { storageState: sharedAuthState } : {}),
      });
      const page = await ctx.newPage();

      try {
        await page.goto(scene.url, { waitUntil: "domcontentloaded", timeout: 20000 });
      } catch (err) {
        console.log(`  ⚠️  goto ${scene.url} failed: ${(err as Error).message.slice(0, 120)}`);
      }
      // Let the page settle a beat before scripted actions begin.
      await page.waitForTimeout(800);

      await runActions(page, scene.actions);

      // Hold the last frame until total elapsed matches voiceover + tail.
      const elapsedSec = (Date.now() - start) / 1000;
      const remainingSec = targetSec - elapsedSec;
      if (remainingSec > 0) {
        await page.waitForTimeout(remainingSec * 1000);
      }

      // Capture the video path BEFORE closing the context.
      const video = page.video();
      await ctx.close();
      if (video) {
        const rawPath = await video.path();
        const destPath = path.join(SCENE_DIR, `${scene.id}.webm`);
        try {
          fs.renameSync(rawPath, destPath);
          console.log(`  ✓ saved ${destPath} (${((Date.now() - start) / 1000).toFixed(1)}s)`);
        } catch (err) {
          console.log(`  ⚠️  rename failed (${(err as Error).message}), copying instead`);
          fs.copyFileSync(rawPath, destPath);
        }
      }
    });
  }
});
