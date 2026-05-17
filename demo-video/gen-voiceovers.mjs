#!/usr/bin/env node
/**
 * Hit Murf.ai to generate one MP3 per scene defined in scenes.json.
 * Writes voiceovers/<scene-id>.mp3 and a sidecar voiceovers/<id>.json with duration.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = __dirname;
const VOICE_DIR = path.join(ROOT, "voiceovers");
const SCENES = JSON.parse(fs.readFileSync(path.join(ROOT, "scenes.json"), "utf8"));

const API_KEY = process.env.MURF_API_KEY;
if (!API_KEY) {
  console.error("MURF_API_KEY env var required");
  process.exit(1);
}

const VOICE_ID = process.env.MURF_VOICE_ID || "en-US-natalie";
const FORCE = process.env.FORCE === "1";

fs.mkdirSync(VOICE_DIR, { recursive: true });

async function generateOne(scene) {
  const mp3Path = path.join(VOICE_DIR, `${scene.id}.mp3`);
  const metaPath = path.join(VOICE_DIR, `${scene.id}.json`);
  if (!FORCE && fs.existsSync(mp3Path) && fs.existsSync(metaPath)) {
    const m = JSON.parse(fs.readFileSync(metaPath, "utf8"));
    console.log(`  cached ${scene.id} (${m.duration.toFixed(1)}s)`);
    return m.duration;
  }

  const body = {
    voiceId: VOICE_ID,
    text: scene.voiceover,
    format: "MP3",
    modelVersion: "GEN2",
    sampleRate: 48000,
    rate: -8,
    pitch: 0,
  };

  const res = await fetch("https://api.murf.ai/v1/speech/generate", {
    method: "POST",
    headers: {
      "api-key": API_KEY,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`Murf ${res.status}: ${txt.slice(0, 300)}`);
  }
  const data = await res.json();
  if (!data.audioFile) throw new Error(`No audioFile: ${JSON.stringify(data).slice(0, 200)}`);

  // Download MP3
  const audioRes = await fetch(data.audioFile);
  const buf = Buffer.from(await audioRes.arrayBuffer());
  fs.writeFileSync(mp3Path, buf);
  fs.writeFileSync(
    metaPath,
    JSON.stringify({ id: scene.id, duration: data.audioLengthInSeconds, voiceId: VOICE_ID }, null, 2)
  );
  console.log(`  generated ${scene.id} → ${data.audioLengthInSeconds.toFixed(1)}s (${buf.length} bytes)`);
  return data.audioLengthInSeconds;
}

const durations = {};
for (const scene of SCENES) {
  console.log(`scene ${scene.id} (${scene.title})`);
  try {
    durations[scene.id] = await generateOne(scene);
  } catch (e) {
    console.error(`  FAILED ${scene.id}: ${e.message}`);
    process.exit(2);
  }
}

fs.writeFileSync(
  path.join(VOICE_DIR, "_index.json"),
  JSON.stringify(
    {
      generated_at: new Date().toISOString(),
      total_duration_s: Object.values(durations).reduce((a, b) => a + b, 0),
      scenes: durations,
    },
    null,
    2
  )
);
console.log(`\ntotal ${Object.values(durations).reduce((a, b) => a + b, 0).toFixed(1)}s across ${Object.keys(durations).length} scenes`);
