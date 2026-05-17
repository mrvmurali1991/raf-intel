#!/usr/bin/env node
/**
 * Extract one representative keyframe per scene from the final video,
 * so a reviewer agent can VISUALLY inspect what was actually shown
 * during each scene's voiceover window.
 *
 * Output: demo-video/review/<seq>-<sceneId>.jpg
 * Also writes review/timeline.json describing scene start/end times.
 */
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = __dirname;
const SCENES = JSON.parse(fs.readFileSync(path.join(ROOT, "scenes-v2.json"), "utf8"));
const VOICE_INDEX = JSON.parse(fs.readFileSync(path.join(ROOT, "voiceovers-v2/_index.json"), "utf8"));
const VIDEO = path.join(ROOT, "final/raf-demo-v2.mp4");
const REVIEW_DIR = path.join(ROOT, "review");
fs.mkdirSync(REVIEW_DIR, { recursive: true });

let cursor = 0;
const timeline = [];
for (let i = 0; i < SCENES.length; i++) {
  const s = SCENES[i];
  const dur = VOICE_INDEX.scenes[s.id] || 30;
  // Pick a frame near the scene's tail (85%) — late enough that any
  // animated toast / late-arriving SSE payload / page reload has had time
  // to settle, early enough that the scene isn't crossfading out yet.
  const ts = cursor + dur * 0.85;
  const seq = String(i + 1).padStart(2, "0");
  const outJpg = path.join(REVIEW_DIR, `${seq}-${s.id}.jpg`);
  const r = spawnSync("ffmpeg", [
    "-y",
    "-ss", ts.toFixed(2),
    "-i", VIDEO,
    "-frames:v", "1",
    "-q:v", "3",
    outJpg,
  ], { encoding: "utf8" });
  if (r.status !== 0) {
    console.error(`failed ${s.id}: ${r.stderr?.slice(-300)}`);
  }
  timeline.push({
    seq, id: s.id, title: s.title,
    start_s: +cursor.toFixed(2),
    end_s: +(cursor + dur).toFixed(2),
    snapshot_at_s: +ts.toFixed(2),
    snapshot_jpg: path.relative(ROOT, outJpg),
    voiceover_excerpt: s.voiceover.slice(0, 220) + (s.voiceover.length > 220 ? "..." : ""),
  });
  cursor += dur;
}
fs.writeFileSync(path.join(REVIEW_DIR, "timeline.json"), JSON.stringify({ video: VIDEO, total_s: +cursor.toFixed(2), scenes: timeline }, null, 2));
console.log(`✓ ${timeline.length} keyframes → ${REVIEW_DIR}`);
console.log(`  timeline.json (total ${cursor.toFixed(1)}s)`);
