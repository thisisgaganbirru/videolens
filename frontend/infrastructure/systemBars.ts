import { Capacitor, SystemBars, SystemBarsStyle } from "@capacitor/core";
import type { PaintedTheme, SystemBarsStyler } from "@/domain/ports";

/* Capacitor 8's built-in SystemBars plugin (shipped in @capacitor/core, no
   extra package). Its style names describe the BAR BACKGROUND, not the icons:

     SystemBarsStyle.Light  ("LIGHT") -> dark icons, for a light background
     SystemBarsStyle.Dark   ("DARK")  -> light icons, for a dark background

   (core-plugins.d.ts; on Android it is setAppearanceLight{Status,Navigation}Bars
   (style !== "DARK") in SystemBars.java.) So the page's theme maps straight
   across: light paper -> Light, dark paper -> Dark.

   No `bar` option: omitting it styles the status bar AND the gesture/navigation
   bar together, and both sit over the same paper colour here. The native side
   remembers the style and re-applies it on configuration changes (rotation,
   OS dark-mode flip), so one call per theme change is enough. */
export class CapacitorSystemBarsStyler implements SystemBarsStyler {
  async matchTheme(theme: PaintedTheme): Promise<void> {
    // The web implementation is already a no-op, but skipping the bridge call
    // keeps it out of the browser entirely.
    if (!Capacitor.isNativePlatform()) return;

    try {
      await SystemBars.setStyle({
        style: theme === "dark" ? SystemBarsStyle.Dark : SystemBarsStyle.Light,
      });
    } catch {
      // Cosmetic only - a failed bridge call must never break the page.
    }
  }
}
