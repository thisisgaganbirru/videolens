import { Capacitor, SystemBars, SystemBarsStyle } from "@capacitor/core";
import type { PaintedTheme, SystemBarsStyler } from "@/domain/ports";

/* Capacitor 8's built-in SystemBars plugin (shipped in @capacitor/core, no
   extra package). Its style names describe the BAR BACKGROUND, not the icons:

     SystemBarsStyle.Light   ("LIGHT")   -> dark icons, for a light background
     SystemBarsStyle.Dark    ("DARK")    -> light icons, for a dark background
     SystemBarsStyle.Default ("DEFAULT") -> resolved natively from the OS night
                                            mode (Configuration.uiMode)

   (core-plugins.d.ts; on Android it is setAppearanceLight{Status,Navigation}Bars
   (style !== "DARK") in SystemBars.java.)

   Refinement 2, #2 — what is actually BEHIND the icons depends on the WebView:

   - WebView >= 140: SystemBars passes the insets through and the page paints
     under the bars, so the background is the app's paper. The style follows
     the app theme: light paper -> Light, dark paper -> Dark.
   - WebView < 140 (the API 35 emulator ships 124): no pass-through. The page
     stops at the bars and they show the native window background, which
     follows the OS theme. Following the app theme there put white icons on a
     white bar (system light, app dark). So the style is Default: the native
     side reads the real OS night mode at the moment of the call.

   Default is resolved once per call and stored as LIGHT/DARK, and the activity
   handles `uiMode` itself (no recreate), so an OS theme flip while the app is
   open would keep the old icons. The hook re-applies on a
   `prefers-color-scheme` change and on return to the foreground when
   `followsSystemTheme()` is true.

   Refinement 5 (THM-01b): "the OS night mode" above now means the ACTIVITY's
   night mode, which follows the app's own theme choice (AppCompat default
   night mode, set by NativeThemePlugin and applied in MainActivity before the
   first frame). So DEFAULT and the page agree whatever the OS says; with
   "system" chosen it is the OS, as before.

   Version 140 mirrors WEBVIEW_VERSION_WITH_SAFE_AREA_FIX in SystemBars.java.
   An unreadable user agent counts as modern: that is Capacitor's own default
   path, and the one every current WebView takes. */
const WEBVIEW_WITH_SAFE_AREA_PASSTHROUGH = 140;

/** The Chromium major version in a user agent (`Chrome/124.0…`), or null. */
export function webViewMajorVersion(userAgent: string): number | null {
  const match = /Chrome\/(\d+)/.exec(userAgent);
  return match ? Number(match[1]) : null;
}

/** Whether the bars show the OS-themed window background instead of the page. */
export function barsFollowSystemTheme(major: number | null): boolean {
  return major !== null && major < WEBVIEW_WITH_SAFE_AREA_PASSTHROUGH;
}

export class CapacitorSystemBarsStyler implements SystemBarsStyler {
  private native(): boolean {
    try {
      return Capacitor.isNativePlatform();
    } catch {
      return false;
    }
  }

  followsSystemTheme(): boolean {
    if (!this.native() || typeof navigator === "undefined") return false;
    return barsFollowSystemTheme(webViewMajorVersion(navigator.userAgent));
  }

  async matchTheme(theme: PaintedTheme): Promise<void> {
    // The web implementation is already a no-op, but skipping the bridge call
    // keeps it out of the browser entirely.
    if (!this.native()) return;

    const style = this.followsSystemTheme()
      ? SystemBarsStyle.Default
      : theme === "dark"
        ? SystemBarsStyle.Dark
        : SystemBarsStyle.Light;
    try {
      // No `bar` option: styles the status bar AND the gesture/navigation bar
      // together; both sit over the same background.
      await SystemBars.setStyle({ style });
    } catch {
      // Cosmetic only - a failed bridge call must never break the page.
    }
  }
}
