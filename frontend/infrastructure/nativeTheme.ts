import { Capacitor, registerPlugin } from "@capacitor/core";
import type { NativeThemeMirror, ThemeChoice } from "@/domain/ports";

/* The app module's own Capacitor plugin (android/app/.../NativeThemePlugin.java,
   registered in MainActivity), not an npm package: it stores the choice in
   SharedPreferences and applies it as AppCompat's night mode, live and on the
   next launch before the first frame (refinement 5, THM-01b). Nothing exists
   on the web side, so the browser never calls it. */
type NativeThemePlugin = {
  setPreference(options: { value: ThemeChoice }): Promise<{ changed?: boolean }>;
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
}
