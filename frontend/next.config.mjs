import { readFileSync } from "node:fs";
import { PHASE_DEVELOPMENT_SERVER, PHASE_PRODUCTION_BUILD } from "next/constants.js";
import { apiOriginFrom, securityHeaders } from "./security/csp.mjs";

const isCapacitorBuild = process.env.CAPACITOR_BUILD === "true";

// The running version, for the Releases page lede ("You are on version …").
// Read from package.json — the same field Android's versionName comes from —
// and inlined at build time; only the version string reaches the client.
const { version: appVersion } = JSON.parse(
  readFileSync(new URL("./package.json", import.meta.url), "utf8"),
);

/* 2026-11-20: a production build with no backend URL inlines the
   `http://localhost:8000` fallback (infrastructure/apiBase.ts) and ships an
   app whose every request goes nowhere. The Railway image (frontend/Dockerfile
   passes the service variable as a build arg) and a local build without
   .env.local are refused here, loudly. GitHub Actions sets CI=true: its
   application checks build with the fallback on purpose, and the two jobs
   that ship a build (container publish, Android) check the URL themselves.
   A Docker build does not inherit CI, so the security scan's throwaway image
   passes a `.invalid` placeholder URL (reusable-security-scan.yml). */
function assertApiBaseUrl() {
  if ((process.env.NEXT_PUBLIC_API_BASE_URL || "").trim()) return;
  if (process.env.CI === "true") return;
  throw new Error(
    "NEXT_PUBLIC_API_BASE_URL is blank, so this production build would send every request to " +
      "http://localhost:8000. Set it to the backend's public URL (on Railway, the frontend " +
      "service's variable; locally, copy .env.example to .env.local)."
  );
}

/** @type {(phase: string) => import('next').NextConfig} */
export default function nextConfig(phase) {
  const dev = phase === PHASE_DEVELOPMENT_SERVER;
  if (phase === PHASE_PRODUCTION_BUILD) assertApiBaseUrl();
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
            const headers = securityHeaders({ apiOrigin, dev });
            // The dev deployment's noindex switch (infrastructure/siteOrigin.ts).
            // The header covers what a robots <meta> cannot: images, the
            // manifest, sitemap.xml itself.
            if (process.env.NEXT_PUBLIC_NOINDEX === "1") {
              headers.push({ key: "X-Robots-Tag", value: "noindex, nofollow" });
            }
            return [{ source: "/:path*", headers }];
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
