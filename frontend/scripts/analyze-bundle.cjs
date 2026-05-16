#!/usr/bin/env node
/**
 * Bundle analyzer for Next 16 (webpack) builds.
 *
 * Next 16 no longer prints the per-route "First Load JS" table in the
 * terminal. This script reconstructs it by parsing the prerendered HTML
 * in `.next/server/app/<route>.html` for each route, summing the gzipped
 * sizes of every `/_next/static/chunks/*.js` referenced.
 *
 * Output: prints a Markdown table sorted by First Load JS desc.
 */
const fs = require("fs");
const path = require("path");
const zlib = require("zlib");

const NEXT_DIR = path.resolve(__dirname, "..", ".next");
const APP_SERVER_DIR = path.join(NEXT_DIR, "server", "app");
const CHUNKS_DIR = path.join(NEXT_DIR, "static", "chunks");

function gzippedSize(file) {
  try {
    const buf = fs.readFileSync(file);
    return zlib.gzipSync(buf, { level: 9 }).length;
  } catch {
    return 0;
  }
}

function rawSize(file) {
  try {
    return fs.statSync(file).size;
  } catch {
    return 0;
  }
}

function extractChunksFromHtml(htmlPath) {
  const html = fs.readFileSync(htmlPath, "utf8");
  const re = /\/_next\/static\/chunks\/([^"\s>]+\.js)/g;
  const set = new Set();
  let m;
  while ((m = re.exec(html)) !== null) set.add(m[1]);
  return [...set];
}

function fmtKB(bytes) {
  return (bytes / 1024).toFixed(1) + " kB";
}

// Build chunk size cache
const chunkSizes = new Map();
function sizeOf(chunkRel) {
  if (chunkSizes.has(chunkRel)) return chunkSizes.get(chunkRel);
  const full = path.join(CHUNKS_DIR, chunkRel);
  const s = { raw: rawSize(full), gz: gzippedSize(full) };
  chunkSizes.set(chunkRel, s);
  return s;
}

// Enumerate .html files in .next/server/app at any depth
function walk(dir, baseRoute = "") {
  const out = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      out.push(...walk(full, baseRoute + "/" + entry.name));
    } else if (entry.isFile() && entry.name.endsWith(".html")) {
      const stem = entry.name.replace(/\.html$/, "");
      const route = stem === "index" ? baseRoute || "/" : (baseRoute ? baseRoute + "/" + stem : "/" + stem);
      out.push({ route, htmlPath: full });
    }
  }
  return out;
}

const routes = walk(APP_SERVER_DIR);

const rows = [];
for (const { route, htmlPath } of routes) {
  const chunks = extractChunksFromHtml(htmlPath);
  let rawTotal = 0;
  let gzTotal = 0;
  for (const c of chunks) {
    const s = sizeOf(c);
    rawTotal += s.raw;
    gzTotal += s.gz;
  }
  rows.push({ route, chunkCount: chunks.length, rawTotal, gzTotal, chunks });
}

// Compute shared baseline: chunks present in every route
let sharedChunks = null;
for (const r of rows) {
  if (sharedChunks === null) sharedChunks = new Set(r.chunks);
  else for (const c of [...sharedChunks]) if (!r.chunks.includes(c)) sharedChunks.delete(c);
}
sharedChunks = sharedChunks || new Set();
let sharedRaw = 0,
  sharedGz = 0;
for (const c of sharedChunks) {
  const s = sizeOf(c);
  sharedRaw += s.raw;
  sharedGz += s.gz;
}

rows.sort((a, b) => b.rawTotal - a.rawTotal);

console.log("# Per-route First Load JS (parsed from prerendered HTML)\n");
console.log(`Shared baseline (chunks loaded on every route): ${sharedChunks.size} chunks, ${fmtKB(sharedRaw)} raw / ${fmtKB(sharedGz)} gzipped\n`);
console.log("| Rank | Route | Chunks | First Load JS (raw) | (gzip) |");
console.log("|------|-------|--------|---------------------|--------|");
rows.forEach((r, i) => {
  console.log(`| ${i + 1} | ${r.route} | ${r.chunkCount} | ${fmtKB(r.rawTotal)} | ${fmtKB(r.gzTotal)} |`);
});

// Heaviest unique (non-shared) chunks
console.log("\n## Heaviest chunks (raw)\n");
const allChunks = [...chunkSizes.entries()]
  .map(([name, s]) => ({ name, raw: s.raw, gz: s.gz }))
  .sort((a, b) => b.raw - a.raw)
  .slice(0, 15);
console.log("| Chunk | Raw | Gzip |");
console.log("|-------|-----|------|");
for (const c of allChunks) console.log(`| ${c.name} | ${fmtKB(c.raw)} | ${fmtKB(c.gz)} |`);

// Emit JSON for downstream use
fs.writeFileSync(
  path.join(__dirname, "..", ".next", "bundle-audit.json"),
  JSON.stringify({ sharedBaseline: { chunks: [...sharedChunks], raw: sharedRaw, gz: sharedGz }, rows, allChunks }, null, 2),
);
