import { App } from "@capacitor/app";
import { Capacitor, type PluginListenerHandle } from "@capacitor/core";
import type { NativeShell } from "@/domain/ports";

/* The Android hardware back button, through @capacitor/app (already installed
   for the update check). Registering a `backButton` listener switches off
   Capacitor's default handling (WebView history back, else exit), so the
   listener has to cover every case itself — see `decideBack` in
   application/backNavigation.ts. Not native → nothing is registered and the
   browser keeps its own back behaviour. */
export class CapacitorNativeShell implements NativeShell {
  isNative(): boolean {
    try {
      return Capacitor.isNativePlatform();
    } catch {
      return false;
    }
  }

  onBackButton(handler: (canGoBack: boolean) => void): () => void {
    if (!this.isNative()) return () => {};
    let handle: PluginListenerHandle | null = null;
    let removed = false;
    App.addListener("backButton", ({ canGoBack }) => handler(canGoBack))
      .then((h) => {
        if (removed) void h.remove();
        else handle = h;
      })
      .catch(() => {
        /* no bridge: Capacitor's default back handling stays in charge */
      });
    return () => {
      removed = true;
      if (handle) void handle.remove();
    };
  }

  /* Refinement 9: `resume` from @capacitor/app, so state that can go stale
     while the app sits in the background (the free-run count, which resets at
     UTC midnight) is read again on return. The WebView also fires
     `visibilitychange`, but the App event is the native shell's own word. */
  onResume(handler: () => void): () => void {
    if (!this.isNative()) return () => {};
    let handle: PluginListenerHandle | null = null;
    let removed = false;
    App.addListener("resume", () => handler())
      .then((h) => {
        if (removed) void h.remove();
        else handle = h;
      })
      .catch(() => {
        /* no bridge: visibilitychange still covers it */
      });
    return () => {
      removed = true;
      if (handle) void handle.remove();
    };
  }

  exitApp(): void {
    void App.exitApp().catch(() => {});
  }
}
