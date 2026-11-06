#!/usr/bin/env node
/**
 * Puts the static export's per-segment RSC files where the client asks for them.
 *
 *   node scripts/fix-export-segments.mjs   # after `next build` with output: "export"
 *
 * Why this exists (refinement 8): with `output: "export"`, the App Router
 * prefetches each route segment from a flat file next to the route, e.g.
 * `/app/__next.app.__PAGE__.txt` (segment path `/app/__PAGE__`, every `/`
 * turned into `.`; next/dist/shared/lib/segment-cache/segment-value-encoding.js).
 * Next 16.4's exporter (next/dist/export/index.js, collectSegmentPaths) lists
 * the segment files with `path.relative`, which returns `app\__PAGE__…` on
 * Windows; only `/` is replaced, and `path.join` then reads the backslash as a
 * separator. So a build on Windows writes `out/app/__next.app/__PAGE__.txt`,
 * a nested directory nobody requests, and every `__PAGE__` prefetch misses
 * (Capacitor logs "Unable to open asset URL: /app/__next.app.__PAGE__.txt").
 * Linux and macOS builds, including CI's release APK, write the flat name and
 * are untouched: there, no `__next.*` directory exists and this is a no-op.
 *
 * The fix is mechanical: every file under a directory named `__next.<…>` moves
 * to the flat name the client builds, `<dir>.<relative path with "/" → ".">`,
 * and the emptied directory is removed. Nothing else in `out/` is touched.
 */

import { existsSync } from "node:fs";
import { mkdir, readdir, rename, rm } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const outDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "out");

if (!existsSync(outDir)) {
  console.error(`fix-export-segments: no export at ${outDir}; run \`next build\` with CAPACITOR_BUILD=true first`);
  process.exit(1);
}

async function filesUnder(dir) {
  const found = [];
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) found.push(...(await filesUnder(full)));
    else found.push(full);
  }
  return found;
}

let moved = 0;

async function walk(dir) {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    const full = path.join(dir, entry.name);
    if (entry.name === "_next") continue; // chunks and media, never segment data
    if (!entry.name.startsWith("__next.")) {
      await walk(full);
      continue;
    }
    for (const file of await filesUnder(full)) {
      const rel = path.relative(full, file).split(path.sep).join(".");
      const dest = path.join(dir, `${entry.name}.${rel}`);
      await mkdir(path.dirname(dest), { recursive: true });
      await rename(file, dest);
      moved += 1;
    }
    await rm(full, { recursive: true, force: true });
  }
}

await walk(outDir);
console.log(
  moved
    ? `fix-export-segments: flattened ${moved} segment file(s) to the names the client requests`
    : "fix-export-segments: nothing to flatten (segment files already flat)",
);
