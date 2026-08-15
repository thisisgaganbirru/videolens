/** @type {import('next').NextConfig} */
const nextConfig = {
  output: process.env.CAPACITOR_BUILD === "true" ? "export" : "standalone",
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
