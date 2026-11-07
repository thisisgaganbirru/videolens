import { readFileSync } from "node:fs";
import { PHASE_DEVELOPMENT_SERVER } from "next/constants.js";
import { apiOriginFrom, securityHeaders } from "./security/csp.mjs";

const isCapacitorBuild = process.env.CAPACITOR_BUILD === "true";

// The running version, for the Releases page lede ("You are on version …").
// Read from package.json — the same field Android's versionName comes from —
// and inlined at build time; only the version string reaches the client.
const { version: appVersion } = JSON.parse(
  readFileSync(new URL("./package.json", import.meta.url), "utf8"),
);

/** @type {(phase: string) => import('next').NextConfig} */
export default function nextConfig(phase) {
  const dev = phase === PHASE_DEVELOPMENT_SERVER;
  return {
    output: isCapacitorBuild ? "export" : "standalone",
    env: {
      NEXT_PUBLIC_APP_VERSION: appVersion,
    },
    images: {
      unoptimized: true,
    },
    poweredByHeader: false,
    // Security headers for the web build only. A static export has no server
    // to send them (Next warns if headers() is set there), so the Capacitor
    // build gets the same policy as a <meta> tag from scripts/inject-csp.mjs.
    // The backend origin comes from NEXT_PUBLIC_API_BASE_URL, the same value
    // the client bundle inlines (infrastructure/apiBase.ts). See
    // security/csp.mjs and docs/frontend/security-headers.md.
    ...(isCapacitorBuild
      ? {}
      : {
          async headers() {
            const apiOrigin = apiOriginFrom(process.env.NEXT_PUBLIC_API_BASE_URL);
            return [{ source: "/:path*", headers: securityHeaders({ apiOrigin, dev }) }];
          },
        }),
    // `next dev` otherwise writes frontend/AGENTS.md and frontend/CLAUDE.md on
    // every start. This repo keeps agent instructions in the root CLAUDE.md only
    // — a subdirectory CLAUDE.md is auto-loaded as a second, Next-controlled
    // instruction source competing with it. The generator emits both files
    // together, so this switch is the only way to stop the CLAUDE.md half.
    agentRules: false,
  };
}
