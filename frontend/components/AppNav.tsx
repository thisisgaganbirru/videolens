"use client";

import { useCallback, useEffect, useState, type MouseEvent } from "react";
import Link from "next/link";
import {
  Film,
  History as HistoryIcon,
  KeyRound,
  Menu,
  ScrollText,
  X,
} from "lucide-react";
import ThemeToggle from "@/components/ThemeToggle";
import { MAIN_TABS, mainTabHref, type MainTab } from "@/application/useMainTab";

/* Hallmark · theme: Terminal (locked) · nav: N5 floating pill
 *
 * The whole nav band — brand, the four destinations, the mobile drawer, the
 * theme toggle — as one component every route renders.
 *
 * It exists now because the tabs became addressable. While the active tab was
 * React state inside HomeScreen, a shared nav was impossible: HomeScreen could
 * never have used it (only HomeScreen could route the tabs), so extracting one
 * would have produced a second canonical chrome for the standalone routes to
 * drift with — exactly what `legal-offline-routes.md` argued against. With the
 * tab in the URL, HomeScreen is just another caller, and there is one nav.
 *
 * Icon + label rows in a drawer on mobile, an inline pill strip on desktop;
 * both shapes are `.nav-tab` in `globals.css`, keyed only off `aria-current`,
 * so the same markup serves both.
 */

const TAB_META: Record<MainTab, { label: string; icon: typeof Film }> = {
  analyze: { label: "analyze", icon: Film },
  history: { label: "history", icon: HistoryIcon },
  "api-key": { label: "api key", icon: KeyRound },
  releases: { label: "releases", icon: ScrollText },
};

type AppNavProps = {
  /** The tab this route *is*, or `null` on a route that is none of them. */
  activeTab: MainTab | null;
  /**
   * Supplied only by the route that already renders the tabs (`/`). It swaps
   * the anchor's navigation for an in-place URL update so the shell is never
   * unmounted. Everywhere else the href *is* the navigation, which is why the
   * tabs are real links and not buttons: on `/privacy` there is genuinely a
   * document to fetch, and middle-click, ctrl-click and "copy link address"
   * all have to keep working on both.
   */
  onSelectTab?: (tab: MainTab) => void;
};

/** Anything the browser would rather handle itself than let us intercept. */
function isPlainLeftClick(event: MouseEvent<HTMLAnchorElement>): boolean {
  return (
    event.button === 0 &&
    !event.metaKey &&
    !event.ctrlKey &&
    !event.shiftKey &&
    !event.altKey
  );
}

export default function AppNav({ activeTab, onSelectTab }: AppNavProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const closeMenu = useCallback(() => setMenuOpen(false), []);

  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeMenu();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menuOpen, closeMenu]);

  const handleTabClick = (tab: MainTab) => (event: MouseEvent<HTMLAnchorElement>) => {
    closeMenu();
    if (!onSelectTab || !isPlainLeftClick(event)) return;
    event.preventDefault();
    onSelectTab(tab);
  };

  return (
    /* The drawer's open state sits here rather than on `.shell` so the nav owns
       everything the nav draws. `.nav-wrap` must stay unpositioned — the drawer
       resolves its inset against `.viewport`, and a containing block here is
       the bug that once trapped it inside the nav pill. */
    <div className="nav-wrap" data-menu-open={menuOpen ? "true" : "false"}>
      <nav className="nav" aria-label="Main">
        <span className="wordmark">videolens</span>
        <div className="nav-right">
          <div className="menu-scrim" aria-hidden="true" onClick={closeMenu} />

          <div className="nav-links" id="nav-links">
            {/* Only rendered inside the mobile drawer, which covers the nav
                row, so it carries its own wordmark and close. */}
            <div className="menu-head">
              <span className="wordmark">videolens</span>
              <button
                type="button"
                className="menu-close"
                onClick={closeMenu}
                aria-label="Close menu"
              >
                <X aria-hidden="true" />
              </button>
            </div>
            {MAIN_TABS.map((tab) => {
              const { label, icon: Icon } = TAB_META[tab];
              return (
                <Link
                  key={tab}
                  className="nav-tab"
                  href={mainTabHref(tab)}
                  aria-current={activeTab === tab ? "page" : undefined}
                  onClick={handleTabClick(tab)}
                >
                  <Icon aria-hidden="true" />
                  {label}
                </Link>
              );
            })}
          </div>

          <button
            type="button"
            className="menu-toggle"
            onClick={() => setMenuOpen((open) => !open)}
            aria-expanded={menuOpen}
            aria-controls="nav-links"
            aria-label="Menu"
          >
            {menuOpen ? <X aria-hidden="true" /> : <Menu aria-hidden="true" />}
          </button>

          <ThemeToggle />
        </div>
      </nav>
    </div>
  );
}
