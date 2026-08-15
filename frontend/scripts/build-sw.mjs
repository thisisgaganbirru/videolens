#!/usr/bin/env node
/**
 * Generates the served service worker from `sw/sw.template.js`.
 *
 *   node scripts/build-sw.mjs            # after `next build` (standalone)
 *   node scripts/build-sw.mjs --export   # after `next build` with output: "export"
 *
 * Why this exists: Next content-hashes every client chunk filename, so a
 * hand-maintained precache list can name the shell's HTML but never its JS.
 * The result was a service worker that served a page offline which then never
 * hydrated — every client control rendered and did nothing. Hardcoding a hash
 * is not a fix; it is correct for one build and silently rots on the next.
 *
 * Deliberately dependency-free. The whole job is "read the build output, list
 * the assets, digest them, substitute two tokens" — Workbox's value is its
 * runtime routing DSL, which a 90-line two-rule worker does not need, and
 * adopting it would mean rewriting the policy the template documents.
 *
 * Fails loudly (exit 1) on a missing or empty build directory. A service
 * worker with a partial precache looks like it works until the one missing
 * chunk is needed, so "generated nothing, shipped anyway" must never be a
 * silent outcome.
 */

import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
import { readdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const isExport = process.argv.includes("--export");

const templatePath = path.join(frontendDir, "sw", "sw.template.js");

/* Scan whatever this build actually produced, never the other mode's leftovers:
 * a stale `out/` from an earlier mobile build would otherwise contribute chunk
 * names the standalone build never emitted. */
const buildRoot = isExport ? path.join(frontendDir, "out") : path.join(frontendDir, ".next");
const staticDir = isExport
  ? path.join(buildRoot, "_next", "static")
  : path.join(buildRoot, "static");

/* The prerendered HTML for the four precached routes. Its bytes go into the
 * cache digest because the documents themselves are not content-hashed — a copy
 * change with no chunk change still has to invalidate the old cache. */
const htmlDir = isExport ? buildRoot : path.join(buildRoot, "server", "app");
const documentHtml = [
  ["/", "index.html"],
  ["/offline", "offline.html"],
  ["/privacy", "privacy.html"],
  ["/terms", "terms.html"],
].map(([route, file]) => [route, path.join(htmlDir, file)]);

function die(message) {
  console.error(`build-sw: ${message}`);
  process.exit(1);
}

async function collectAssets(dir, prefix = "") {
  const entries = await readdir(dir, { withFileTypes: true });
  const found = [];
  for (const entry of entries) {
    const rel = prefix ? `${prefix}/${entry.name}` : entry.name;
    if (entry.isDirectory()) {
      found.push(...(await collectAssets(path.join(dir, entry.name), rel)));
    } else if (/\.(js|css)$/.test(entry.name)) {
      found.push(`/_next/static/${rel}`);
    }
  }
  return found;
}

if (!existsSync(templatePath)) die(`template missing at ${templatePath}`);
if (!existsSync(staticDir)) {
  die(`no build output at ${staticDir} — run \`next build\`${isExport ? " with CAPACITOR_BUILD=true" : ""} first`);
}

const assets = (await collectAssets(staticDir)).sort();
if (assets.length === 0) die(`no .js/.css assets found under ${staticDir}`);

/* Digest = the exact precached set, so any change to a chunk name or to a
 * precached document changes the cache name and the activate handler drops the
 * old cache instead of pairing new HTML with chunks that no longer exist.
 *
 * Measured, not assumed: this changes on EVERY build, because Next's buildId is
 * random by default and is itself a path segment in three of the precached
 * assets. So the cost is a full ~1 MB re-precache per deploy even when nothing
 * changed. That is the safe direction — it over-invalidates, never under — and
 * making it content-derived would mean pinning `generateBuildId`, which changes
 * what the build ID means everywhere else. */
const digest = createHash("sha256");
for (const asset of assets) digest.update(`${asset}\n`);
for (const [route, file] of documentHtml) {
  if (!existsSync(file)) die(`precached route ${route} has no prerendered HTML at ${file}`);
  digest.update(route);
  digest.update(await readFile(file));
}
const cacheName = `videolens-shell-${digest.digest("hex").slice(0, 12)}`;

const template = await readFile(templatePath, "utf8");
for (const token of ["__CACHE_NAME__", "__BUILD_ASSETS__"]) {
  if (!template.includes(token)) die(`template no longer contains ${token}`);
}

const generated = template
  .replace("__CACHE_NAME__", cacheName)
  .replace("__BUILD_ASSETS__", JSON.stringify(assets, null, 2));

/* `public/sw.js` is what `next start` serves; `out/sw.js` is what the static
 * export ships. The export copies `public/` during the build, i.e. before this
 * script runs, so writing only one of the two would ship the previous build's
 * worker. */
const targets = [path.join(frontendDir, "public", "sw.js")];
if (isExport) targets.push(path.join(buildRoot, "sw.js"));

for (const target of targets) {
  await writeFile(target, generated, "utf8");
  console.log(`build-sw: wrote ${path.relative(frontendDir, target)}`);
}
console.log(`build-sw: ${cacheName} · ${assets.length} build assets precached`);
