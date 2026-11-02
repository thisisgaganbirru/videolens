import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  appId: "ai.videolens.app",
  appName: "VideoLens AI",
  webDir: "out",
  android: {
    allowMixedContent: false,
    // Light `--color-paper` (app/tokens.css): the WebView's colour before the
    // first paint. One value only, so it cannot follow the OS; the pre-paint
    // script stamps the real theme before the page's first frame.
    backgroundColor: "#F6F4EE",
  },
  plugins: {
    SystemBars: {
      insetsHandling: "css",
      // First-paint fallback only. Names describe the bar BACKGROUND; "DEFAULT"
      // resolves from the OS night mode, which is both what the bars sit over
      // on WebView < 140 and the app's own default theme since refinement 2
      // (no stored choice = follow the device). Was "LIGHT" while the default
      // theme was light. The runtime sync (application/useSystemBarsTheme.ts)
      // takes over once JS runs. Native config: lands on the next cap sync.
      style: "DEFAULT",
      hidden: false,
      animation: "NONE",
    },
  },
};

export default config;
