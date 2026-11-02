import { Capacitor, registerPlugin, type PluginListenerHandle } from "@capacitor/core";
import type { NativeThemeMirror, ThemeChoice } from "@/domain/ports";

/* The app module's own Capacitor plugin (android/app/.../NativeThemePlugin.java,
   registered in MainActivity), not an npm package: it stores the choice in
   SharedPreferences and applies it as AppCompat's night mode, live and on the
   next launch before the first frame (refinement 5, THM-01b). Since
   refinement 7 (THM-01b-6) it also reports the OS's own night state, which the
   WebView's prefers-color-scheme stops tracking once the app has forced a
   mode. Nothing exists on the web side, so the browser never calls it. */
type NativeThemePlugin = {
  setPreference(options: { value: ThemeChoice }): Promise<{ changed?: boolean }>;
  getSystemNight(): Promise<{ dark?: boolean }>;
  addListener(
    eventName: "systemNightChanged",
    listener: (event: { dark?: boolean }) => void,
  ): Promise<PluginListenerHandle>;
};

const NativeTheme = registerPlugin<NativeThemePlugin>("NativeTheme");

export class CapacitorNativeThemeMirror implements NativeThemeMirror {
  private native(): boolean {
    try {
      return Capacitor.getPlatform() === "android";
    } catch {
      return false;
    }
  }

  async setPreference(choice: ThemeChoice): Promise<boolean> {
    if (!this.native()) return false;
    try {
      const result = await NativeTheme.setPreference({ value: choice });
      return result?.changed === true;
    } catch {
      /* An APK older than the plugin, or no bridge: cosmetic only. */
      return false;
    }
  }

  async systemNight(): Promise<boolean | null> {
    if (!this.native()) return null;
    try {
      const result = await NativeTheme.getSystemNight();
      return typeof result?.dark === "boolean" ? result.dark : null;
    } catch {
      /* An APK older than refinement 7: the caller keeps matchMedia. */
      return null;
    }
  }

  onSystemNightChange(listener: (dark: boolean) => void): () => void {
    if (!this.native()) return () => {};
    let handle: PluginListenerHandle | null = null;
    let removed = false;
    void NativeTheme.addListener("systemNightChanged", (event) => {
      if (!removed && typeof event?.dark === "boolean") listener(event.dark);
    })
      .then((h) => {
        if (removed) void h.remove();
        else handle = h;
      })
      .catch(() => {
        /* No plugin in this APK: nothing to listen to. */
      });
    return () => {
      removed = true;
      if (handle) void handle.remove();
    };
  }
}
