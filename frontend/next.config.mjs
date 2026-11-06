import { readFileSync } from "node:fs";

const isCapacitorBuild = process.env.CAPACITOR_BUILD === "true";

// The running version, for the Releases page lede ("You are on version …").
// Read from package.json — the same field Android's versionName comes from —
// and inlined at build time; only the version string reaches the client.
const { version: appVersion } = JSON.parse(
  readFileSync(new URL("./package.json", import.meta.url), "utf8"),
);

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: isCapacitorBuild ? "export" : "standalone",
  env: {
    NEXT_PUBLIC_APP_VERSION: appVersion,
  },
  images: {
    unoptimized: true,
  },
  // `next dev` otherwise writes frontend/AGENTS.md and frontend/CLAUDE.md on
  // every start. This repo keeps agent instructions in the root CLAUDE.md only
  // — a subdirectory CLAUDE.md is auto-loaded as a second, Next-controlled
  // instruction source competing with it. The generator emits both files
  // together, so this switch is the only way to stop the CLAUDE.md half.
  agentRules: false,
};

export default nextConfig;
