#!/usr/bin/env node
/**
 * Writes a hash-based Content-Security-Policy `<meta>` into every prerendered
 * document.
 *
 *   node scripts/inject-csp.mjs            # after `next build` (standalone)
 *   node scripts/inject-csp.mjs --export   # after `next build` with output: "export"
 *
 * Why this exists: Next's App Router inlines `self.__next_f.push(…)` RSC
 * scripts, and the root layout inlines the pre-paint script. Nonces would
 * need per-request rendering, and every page here is static. But a static
 * page's inline scripts are fixed at build time, so each document can carry
 * the SHA-256 of exactly the scripts it contains, and nothing else runs.
 * The policy itself lives in `security/csp.mjs`; see that file and
 * docs/frontend/security-headers.md.
 *
 * Must run BEFORE scripts/build-sw.mjs: the service worker's cache name
 * digests these documents' bytes.
 *
 * Fails loudly (exit 1) when there is nothing to process, so a build that
 * silently ships pages without the policy cannot happen.
 */

import { existsSync } from "node:fs";
import { readdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import nextEnv from "@next/env";
import {
  apiOriginFrom,
  exportMetaPolicy,
  inlineScriptHashes,
  webMetaPolicy,
  withMetaPolicy,
} from "../security/csp.mjs";

const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const isExport = process.argv.includes("--export");

/* The same .env files `next build` read, so the backend origin in the policy
   is the one the bundle was built against. */
nextEnv.loadEnvConfig(frontendDir, false, { info: () => {}, error: console.error });
const apiOrigin = apiOriginFrom(process.env.NEXT_PUBLIC_API_BASE_URL);

function die(message) {
  console.error(`inject-csp: ${message}`);
  process.exit(1);
}

/* Web: the prerendered pages, and the standalone server's copy of them (the
   one the Docker image actually serves). Export: the whole `out/` tree. */
const roots = isExport
  ? [path.join(frontendDir, "out")]
  : [
      path.join(frontendDir, ".next", "server", "app"),
      path.join(frontendDir, ".next", "standalone", ".next", "server", "app"),
    ];

async function htmlUnder(dir) {
  const found = [];
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) found.push(...(await htmlUnder(full)));
    else if (entry.name.endsWith(".html")) found.push(full);
  }
  return found;
}

let total = 0;
for (const root of roots) {
  if (!existsSync(root)) die(`no build output at ${root}`);
  const files = await htmlUnder(root);
  if (files.length === 0) die(`no prerendered .html under ${root}`);
  for (const file of files) {
    const html = await readFile(file, "utf8");
    const scriptHashes = inlineScriptHashes(html);
    const policy = isExport
      ? exportMetaPolicy({ apiOrigin, scriptHashes })
      : webMetaPolicy({ scriptHashes });
    try {
      await writeFile(file, withMetaPolicy(html, policy), "utf8");
    } catch (error) {
      die(`${path.relative(frontendDir, file)}: ${error.message}`);
    }
    total += 1;
    console.log(
      `inject-csp: ${path.relative(frontendDir, file)} · ${scriptHashes.length} inline script hash(es)`,
    );
  }
}
console.log(`inject-csp: ${total} document(s) · connect-src backend ${apiOrigin}`);
