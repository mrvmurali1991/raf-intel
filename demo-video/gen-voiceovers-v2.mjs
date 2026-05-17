#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = __dirname;
const VOICE_DIR = path.join(ROOT, "voiceovers-v2");
const SCENES = JSON.parse(fs.readFileSync(path.join(ROOT, "scenes-v2.json"), "utf8"));
const API_KEY = process.env.MURF_API_KEY;
if (!API_KEY) { console.error("MURF_API_KEY required"); process.exit(1); }
const VOICE_ID = process.env.MURF_VOICE_ID || "en-US-natalie";
const FORCE = process.env.FORCE === "1";

fs.mkdirSync(VOICE_DIR, { recursive: true });

async function gen(scene) {
  const mp3Path = path.join(VOICE_DIR, `${scene.id}.mp3`);
  const metaPath = path.join(VOICE_DIR, `${scene.id}.json`);
  if (!FORCE && fs.existsSync(mp3Path) && fs.existsSync(metaPath)) {
    return JSON.parse(fs.readFileSync(metaPath, "utf8")).duration;
  }
  const res = await fetch("https://api.murf.ai/v1/speech/generate", {
    method: "POST",
    headers: { "api-key": API_KEY, "Content-Type": "application/json" },
    body: JSON.stringify({
      voiceId: VOICE_ID,
      text: scene.voiceover,
      format: "MP3",
      modelVersion: "GEN2",
      sampleRate: 48000,
      rate: -8,
    }),
  });
  if (!res.ok) throw new Error(`Murf ${res.status}: ${(await res.text()).slice(0, 200)}`);
  const data = await res.json();
  const audioRes = await fetch(data.audioFile);
  fs.writeFileSync(mp3Path, Buffer.from(await audioRes.arrayBuffer()));
  fs.writeFileSync(metaPath, JSON.stringify({ id: scene.id, duration: data.audioLengthInSeconds }, null, 2));
  return data.audioLengthInSeconds;
}

const durations = {};
for (const s of SCENES) {
  console.log(`▸ ${s.id}`);
  try { durations[s.id] = await gen(s); console.log(`  ${durations[s.id].toFixed(1)}s`); }
  catch (e) { console.error(`  FAIL: ${e.message}`); process.exit(2); }
}
fs.writeFileSync(
  path.join(VOICE_DIR, "_index.json"),
  JSON.stringify({ total: Object.values(durations).reduce((a, b) => a + b, 0), scenes: durations }, null, 2)
);
console.log(`\ntotal ${Object.values(durations).reduce((a, b) => a + b, 0).toFixed(1)}s`);
