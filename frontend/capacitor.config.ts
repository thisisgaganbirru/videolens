import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  appId: "ai.videolens.app",
  appName: "VideoLens AI",
  webDir: "out",
  android: {
    allowMixedContent: false,
    // Light `--color-paper` (app/tokens.css): the WebView's colour before the
    // first paint, so it should match the first-run (light) theme.
    backgroundColor: "#F6F4EE",
  },
  plugins: {
    SystemBars: {
      insetsHandling: "css",
      // First-paint fallback only. Names describe the bar BACKGROUND: "LIGHT"
      // = dark icons. Matches DEFAULT_THEME (light) in components/theme.ts;
      // was "DARK" (white icons), invisible on the light paper. The runtime
      // sync (application/useSystemBarsTheme.ts) takes over once JS runs and
      // follows the theme toggle. Native config: lands on the next cap run.
      style: "LIGHT",
      hidden: false,
      animation: "NONE",
    },
  },
};

export default config;
