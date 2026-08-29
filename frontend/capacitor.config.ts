import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  appId: "ai.videolens.app",
  appName: "VideoLens AI",
  webDir: "out",
  android: {
    allowMixedContent: false,
    backgroundColor: "#0b0d0c",
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
