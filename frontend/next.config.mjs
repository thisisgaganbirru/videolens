const isCapacitorBuild = process.env.CAPACITOR_BUILD === "true";

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: isCapacitorBuild ? "export" : "standalone",
  images: {
    unoptimized: true,
  },
  // `next dev` otherwise writes frontend/AGENTS.md and frontend/CLAUDE.md on
  // every start. This repo keeps agent instructions in the root CLAUDE.md only
  // — a subdirectory CLAUDE.md is auto-loaded as a second, Next-controlled
  // instruction source competing with it. The generator emits both files
  // together, so this switch is the only way to stop the CLAUDE.md half.
  agentRules: false,
  // The installed Android app is served from the Capacitor WebView origin
  // (https://localhost) and fetches this manifest from the deployed web app to
  // find out whether a newer build exists, so the read is cross-origin and
  // needs to be allowed explicitly. It is public release metadata — version
  // number and a link to a release page — and carries nothing user-specific,
  // so `*` costs nothing here. A plain GET with no custom headers is a CORS
  // "simple request", so this is never preflighted.
  //
  // Spread rather than declared outright because `headers()` requires a server
  // and the Capacitor build is `output: "export"`, which has none.
  ...(isCapacitorBuild
    ? {}
    : {
        async headers() {
          return [
            {
              source: "/version.json",
              headers: [{ key: "Access-Control-Allow-Origin", value: "*" }],
            },
          ];
        },
      }),
};

export default nextConfig;
