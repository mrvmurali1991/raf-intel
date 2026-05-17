#!/usr/bin/env node
/**
 * v2 assembler — hard-syncs each scene's video to its voiceover length
 * by re-encoding (not copy) and setting -t to the audio duration. This
 * eliminates the audio-drift problem of the v1 assembler.
 *
 * For every scene:
 *   1. ffprobe audio mp3 → audio duration A
 *   2. ffmpeg: video webm → 1440x900 H.264 25fps, padded with last-frame
 *      clone (tpad) if shorter than A, trimmed if longer, audio = mp3,
 *      output duration locked to A via `-t A`
 *   3. Write to final/_per-scene-v2/<id>.mp4
 * Then concat-mux all per-scene mp4s into final/raf-demo-v2.mp4 using a
 * single ffmpeg call with the concat filter (NOT demuxer copy) so all
 * timestamps are regenerated.
 */
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = __dirname;
const SCENES = JSON.parse(fs.readFileSync(path.join(ROOT, "scenes-v2.json"), "utf8"));
const VOICE_DIR = path.join(ROOT, "voiceovers-v2");
const SCENE_DIR = path.join(ROOT, "scenes-v2");
const FINAL_DIR = path.join(ROOT, "final");
const PER_DIR = path.join(FINAL_DIR, "_per-scene-v2");
fs.mkdirSync(FINAL_DIR, { recursive: true });
fs.mkdirSync(PER_DIR, { recursive: true });

function run(cmd, args) {
  const r = spawnSync(cmd, args, { stdio: ["ignore", "pipe", "pipe"], encoding: "utf8" });
  if (r.status !== 0) {
    console.error(`${cmd} ${args.join(" ")} → exit ${r.status}`);
    console.error(r.stderr?.slice(-1500));
    throw new Error(`${cmd} failed`);
  }
}

function ffprobe(file) {
  const r = spawnSync("ffprobe", [
    "-v", "error",
    "-show_entries", "format=duration",
    "-of", "default=noprint_wrappers=1:nokey=1",
    file,
  ], { encoding: "utf8" });
  return parseFloat((r.stdout || "0").trim()) || 0;
}

const perScene = [];
for (const scene of SCENES) {
  const webm = path.join(SCENE_DIR, `${scene.id}.webm`);
  const mp3 = path.join(VOICE_DIR, `${scene.id}.mp3`);
  const outMp4 = path.join(PER_DIR, `${scene.id}.mp4`);

  if (!fs.existsSync(webm)) { console.log(`SKIP ${scene.id} (no video)`); continue; }
  if (!fs.existsSync(mp3))  { console.log(`SKIP ${scene.id} (no audio)`); continue; }

  const vSec = ffprobe(webm);
  const aSec = ffprobe(mp3);
  const target = aSec; // audio is the master clock
  console.log(`▸ ${scene.id}: v=${vSec.toFixed(1)}s a=${aSec.toFixed(1)}s → target ${target.toFixed(1)}s`);

  // tpad: clone last frame for (target - vSec) seconds; if vSec >= target,
  // ffmpeg -t will truncate. Force 25fps, yuv420p, even dims for libx264.
  const padDuration = Math.max(0, target - vSec + 0.5);
  const vfilter = [
    "scale=1440:900:force_original_aspect_ratio=decrease",
    "pad=1440:900:(ow-iw)/2:(oh-ih)/2:color=black",
    "fps=25",
    `tpad=stop_mode=clone:stop_duration=${padDuration.toFixed(2)}`,
    "setpts=PTS-STARTPTS",
  ].join(",");

  run("ffmpeg", [
    "-y",
    "-i", webm,
    "-i", mp3,
    "-vf", vfilter,
    "-c:v", "libx264",
    "-preset", "veryfast",
    "-crf", "23",
    "-pix_fmt", "yuv420p",
    "-c:a", "aac",
    "-b:a", "192k",
    "-ar", "48000",
    "-map", "0:v:0",
    "-map", "1:a:0",
    "-t", target.toFixed(3),
    "-movflags", "+faststart",
    outMp4,
  ]);
  const out = ffprobe(outMp4);
  console.log(`  → ${outMp4} (${out.toFixed(1)}s)`);
  perScene.push({ id: scene.id, mp4: outMp4, dur: out });
}

// Concat using filter (re-encode) so timestamps are clean.
const listFile = path.join(PER_DIR, "_concat.txt");
fs.writeFileSync(
  listFile,
  perScene.map((p) => `file '${p.mp4.replace(/'/g, "'\\''")}'`).join("\n")
);
const finalMp4 = path.join(FINAL_DIR, "raf-demo-v2.mp4");
console.log(`\n📼 concatenating ${perScene.length} scenes → ${finalMp4}`);
// concat demuxer with re-encode for stability (codec params already match).
run("ffmpeg", [
  "-y",
  "-f", "concat",
  "-safe", "0",
  "-i", listFile,
  "-c:v", "libx264",
  "-preset", "veryfast",
  "-crf", "23",
  "-pix_fmt", "yuv420p",
  "-c:a", "aac",
  "-b:a", "192k",
  "-ar", "48000",
  "-movflags", "+faststart",
  finalMp4,
]);
const finalSec = ffprobe(finalMp4);
const stat = fs.statSync(finalMp4);
console.log(`\n✓ ${finalMp4}`);
console.log(`  duration ${finalSec.toFixed(1)}s (${(finalSec / 60).toFixed(1)} min)`);
console.log(`  size ${(stat.size / 1024 / 1024).toFixed(1)} MB`);
