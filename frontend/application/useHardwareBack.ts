"use client";

import { useEffect, useRef } from "react";
import { decideBack } from "@/application/backNavigation";
import { goToMainTab, isAppPath, APP_PATH, type MainTab } from "@/application/useMainTab";
import { nativeShell } from "@/infrastructure/container";

/* The topmost open modal, if any. Native <dialog>s stack in DOM order of
   opening for our two (Welcome, More sheet); the last open one is on top. */
function topDialog(): HTMLDialogElement | null {
  const open = document.querySelectorAll<HTMLDialogElement>("dialog[open]");
  return open.length ? open[open.length - 1] : null;
}

/* Close it the way Escape would: a cancelable `cancel` first, so a dialog
   that handles cancel itself (Welcome records a dismissal) still does, then
   close() unless it said no. */
function cancelDialog(dialog: HTMLDialogElement): void {
  const event = new Event("cancel", { cancelable: true });
  if (dialog.dispatchEvent(event)) dialog.close();
}

/**
 * Android hardware back, native shell only (refinement 1, #4). Mount once per
 * route: `BottomTabBar` does, and every route renders exactly one.
 *
 * Off the native shell `nativeShell.onBackButton` registers nothing, so the
 * browser's own back and the PWA's gesture keep working untouched.
 */
export function useHardwareBack(activeTab: MainTab | null, onSelectTab?: (tab: MainTab) => void): void {
  /* Latest values without re-registering the native listener on every tab
     change. */
  const latest = useRef({ activeTab, onSelectTab });
  useEffect(() => {
    latest.current = { activeTab, onSelectTab };
  });

  useEffect(
    () =>
      nativeShell.onBackButton((canGoBack) => {
        const { activeTab: tab, onSelectTab: select } = latest.current;
        const dialog = topDialog();
        const onApp = isAppPath(window.location.pathname);
        const action = decideBack({
          dialogOpen: dialog !== null,
          canGoBack,
          atRoot: onApp && tab === "analyze",
        });
        switch (action) {
          case "close-dialog":
            if (dialog) cancelDialog(dialog);
            return;
          case "history-back":
            window.history.back();
            return;
          case "go-analyze":
            if (onApp) (select ?? goToMainTab)("analyze");
            else window.location.replace(APP_PATH);
            return;
          case "exit":
            nativeShell.exitApp();
            return;
        }
      }),
    [],
  );
}
