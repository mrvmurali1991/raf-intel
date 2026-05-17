#!/usr/bin/env node
/**
 * Stitch per-scene webm + mp3 → per-scene mp4 (H.264 + AAC),
 * then concat-mux all scene mp4s into final/raf-demo.mp4.
 *
 * Inputs (must exist):
 *   demo-video/scenes/<id>.webm    – Playwright recording
 *   demo-video/voiceovers/<id>.mp3 – Murf voiceover
 *
 * Output:
 *   demo-video/final/raf-demo.mp4
 */
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = __dirname;
const SCENES = JSON.parse(fs.readFileSync(path.join(ROOT, "scenes.json"), "utf8"));
const VOICE_DIR = path.join(ROOT, "voiceovers");
const SCENE_DIR = path.join(ROOT, "scenes");
const FINAL_DIR = path.join(ROOT, "final");
const PER_SCENE_MP4_DIR = path.join(FINAL_DIR, "_per-scene");
fs.mkdirSync(FINAL_DIR, { recursive: true });
fs.mkdirSync(PER_SCENE_MP4_DIR, { recursive: true });

function run(cmd, args, opts = {}) {
  const r = spawnSync(cmd, args, { stdio: "inherit", ...opts });
  if (r.status !== 0) throw new Error(`${cmd} ${args.join(" ")} → ${r.status}`);
}

function ffprobe(file) {
  const r = spawnSync(
    "ffprobe",
    [
      "-v",
      "error",
      "-show_entries",
      "format=duration",
      "-of",
      "default=noprint_wrappers=1:nokey=1",
      file,
    ],
    { encoding: "utf8" }
  );
  return parseFloat((r.stdout || "0").trim()) || 0;
}

const perSceneOutputs = [];
for (const scene of SCENES) {
  const webm = path.join(SCENE_DIR, `${scene.id}.webm`);
  const mp3 = path.join(VOICE_DIR, `${scene.id}.mp3`);
  const outMp4 = path.join(PER_SCENE_MP4_DIR, `${scene.id}.mp4`);

  if (!fs.existsSync(webm)) {
    console.log(`SKIP ${scene.id} — missing video ${webm}`);
    continue;
  }
  if (!fs.existsSync(mp3)) {
    console.log(`SKIP ${scene.id} — missing audio ${mp3}`);
    continue;
  }

  const videoSec = ffprobe(webm);
  const audioSec = ffprobe(mp3);
  // Final length is the longer of the two; video gets a tpad at the end
  // to its last frame, audio is padded with silence via apad. -shortest
  // is NOT used so we never crop the voiceover mid-sentence.
  console.log(`scene ${scene.id}: video ${videoSec.toFixed(1)}s, audio ${audioSec.toFixed(1)}s`);

  // Encode H.264 + AAC, ensure even dimensions for yuv420p, pad video to
  // match audio length if needed, and pad audio to match video if needed.
  const args = [
    "-y",
    "-i",
    webm,
    "-i",
    mp3,
    "-filter_complex",
    `[0:v]scale=1440:900:force_original_aspect_ratio=decrease,pad=1440:900:(ow-iw)/2:(oh-ih)/2:color=black,fps=25,tpad=stop_mode=clone:stop_duration=2[v];[1:a]apad,atrim=0:${Math.max(videoSec, audioSec) + 0.5}[a]`,
    "-map",
    "[v]",
    "-map",
    "[a]",
    "-c:v",
    "libx264",
    "-preset",
    "veryfast",
    "-crf",
    "23",
    "-pix_fmt",
    "yuv420p",
    "-c:a",
    "aac",
    "-b:a",
    "192k",
    "-shortest",
    outMp4,
  ];
  run("ffmpeg", args);
  perSceneOutputs.push(outMp4);
}

// Concatenate all scene mp4s using the concat demuxer.
const listFile = path.join(PER_SCENE_MP4_DIR, "_concat.txt");
fs.writeFileSync(
  listFile,
  perSceneOutputs.map((p) => `file '${p.replace(/'/g, "'\\''")}'`).join("\n")
);
const finalMp4 = path.join(FINAL_DIR, "raf-demo.mp4");
console.log(`\n📼 concatenating ${perSceneOutputs.length} scenes → ${finalMp4}`);
run("ffmpeg", [
  "-y",
  "-f",
  "concat",
  "-safe",
  "0",
  "-i",
  listFile,
  "-c",
  "copy",
  "-movflags",
  "+faststart",
  finalMp4,
]);

const finalSec = ffprobe(finalMp4);
const stat = fs.statSync(finalMp4);
console.log(`\n✓ done — ${finalMp4}`);
console.log(`  duration ${finalSec.toFixed(1)}s (${(finalSec / 60).toFixed(1)} min)`);
console.log(`  size ${(stat.size / 1024 / 1024).toFixed(1)} MB`);
