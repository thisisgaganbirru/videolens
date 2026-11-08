"use client";

import { useRef, useState, type MouseEvent } from "react";
import Link from "next/link";
import { CircleDot, Clock, Ellipsis } from "lucide-react";
import MoreSheet, { sheetOwnsLocation, type LegalRoute } from "@/components/MoreSheet";
import { TAB_LABEL } from "@/components/AppNav";
import { isPlainLeftClick } from "@/components/navClick";
import { setThemePreference, themePreference, type ThemePreference } from "@/components/theme";
import { mainTabHref, type MainTab } from "@/application/useMainTab";
import { useHardwareBack } from "@/application/useHardwareBack";
import { useSoftKeyboard } from "@/application/useSoftKeyboard";

/* Hallmark · theme: editorial · component: bottom tab bar (installed-app shell)
 * states: default · hover · focus · active · current · expanded (More)
 *
 * Analyze, History, More — the App boards' dock. Rendered on every route and
 * shown only when `<html data-shell="app">` (see components/shell.ts); in a
 * browser tab it is display:none, so it is not in the tab order or the
 * accessibility tree there.
 *
 * Analyze and History are the same addressable tabs the top bar uses
 * (`mainTabHref` / `goToMainTab`). More is a button, not a route: it opens the
 * sheet, and owns the sheet's open state so it can be `aria-expanded` and take
 * focus back when the sheet closes.
 */

const DOCK_TABS: { tab: MainTab; icon: typeof Clock }[] = [
  { tab: "analyze", icon: CircleDot },
  { tab: "history", icon: Clock },
];

type BottomTabBarProps = {
  activeTab: MainTab | null;
  /** On a legal route, which one — marks its sheet row and lights up More. */
  currentRoute?: LegalRoute;
  /** Supplied only on `/app`, where a tab switch can update the URL in place. */
  onSelectTab?: (tab: MainTab) => void;
  /** Passed to the More sheet's Account row (auth phase 2). */
  showAccount?: boolean;
};

export default function BottomTabBar({ activeTab, currentRoute, onSelectTab, showAccount = false }: BottomTabBarProps) {
  const sheetRef = useRef<HTMLDialogElement>(null);
  const moreRef = useRef<HTMLButtonElement>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  /* Read from storage (theme.ts) when the sheet opens, not mirrored
     continuously: storage plus <html data-theme> are the one source of truth,
     and while the sheet is open nothing but its own control can change the
     preference — the rest of the page, header toggle included, is inert. */
  const [preference, setPreference] = useState<ThemePreference>("system");

  /* Both mounted here because every route renders exactly one tab bar
     (refinement 1): the hardware back button (Android shell only) and the
     keyboard flag that hides this bar while typing. */
  useHardwareBack(activeTab, onSelectTab);
  useSoftKeyboard();

  const openSheet = () => {
    setPreference(themePreference());
    sheetRef.current?.showModal();
    setSheetOpen(true);
  };

  /* However it closed — Escape, a backdrop tap, a row — focus goes back to the
     control that opened it. */
  const handleSheetClose = () => {
    setSheetOpen(false);
    moreRef.current?.focus();
  };

  const handleChooseTheme = (next: ThemePreference) => {
    setThemePreference(next);
    setPreference(next);
  };

  const handleTabClick = (tab: MainTab) => (event: MouseEvent<HTMLAnchorElement>) => {
    if (!onSelectTab || !isPlainLeftClick(event)) return;
    event.preventDefault();
    onSelectTab(tab);
  };

  return (
    <>
      <nav className="tabbar" aria-label="Main">
        {DOCK_TABS.map(({ tab, icon: Icon }) => (
          <Link
            key={tab}
            className="tabbar-item"
            href={mainTabHref(tab)}
            aria-current={activeTab === tab ? "page" : undefined}
            onClick={handleTabClick(tab)}
          >
            <Icon aria-hidden="true" />
            {TAB_LABEL[tab]}
          </Link>
        ))}
        <button
          ref={moreRef}
          type="button"
          className="tabbar-item"
          aria-haspopup="dialog"
          aria-expanded={sheetOpen}
          aria-controls="more-sheet"
          data-active={sheetOwnsLocation(activeTab, currentRoute) ? "true" : undefined}
          onClick={openSheet}
        >
          <Ellipsis aria-hidden="true" />
          More
        </button>
      </nav>

      <MoreSheet
        ref={sheetRef}
        activeTab={activeTab}
        currentRoute={currentRoute}
        onSelectTab={onSelectTab}
        themePreference={preference}
        onChooseTheme={handleChooseTheme}
        onClose={handleSheetClose}
        showAccount={showAccount}
      />
    </>
  );
}
