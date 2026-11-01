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
      style: "DARK",
      hidden: false,
      animation: "NONE",
    },
  },
};

export default config;
