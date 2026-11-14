"use client";

import { useCallback, useEffect, useRef, useState, type MouseEvent } from "react";
import Link from "next/link";
import { ChevronRight, Menu, UserRound, X } from "lucide-react";
import ThemeToggle from "@/components/ThemeToggle";
import { isPlainLeftClick } from "@/components/navClick";
import { mainTabHref, navTabs, type MainTab } from "@/application/useMainTab";
import type { AccountState } from "@/application/useAccountEntry";

/* Hallmark · theme: editorial (app/tokens.css) · nav: flat top bar
 *
 * The top bar every route renders, in both shells. What it carries depends on
 * the display mode `<html data-shell>` names (see components/shell.ts):
 *
 *  - web, 48rem and up: brand · the destinations · theme toggle (Desktop boards)
 *  - web, below 48rem:  brand · theme toggle · menu toggle, and the four
 *                       destinations in a full-screen menu (Web "Menu" board)
 *
 * Account (auth phase 2) is a fifth destination, drawn only when `showAccount`.
 * From 48rem it is not a text tab but a control at the far right of the bar
 * (after the theme toggle): signed out, a labelled "Sign in" pill (owner,
 * 2026-11-14: the bare person glyph did not say what it did); signed in, a
 * round button with the email's initial. Until the session is known it draws
 * nothing, so neither flashes. The phone menu keeps it as a text row, labelled
 * "Sign in" while signed out.
 *  - app:               brand · theme toggle; the destinations live in the
 *                       bottom tab bar instead (BottomTabBar)
 *
 * All of it is always rendered and CSS hides what a mode doesn't use, with
 * display:none — so the hidden parts are out of the tab order and the
 * accessibility tree, not just out of sight.
 */

export const TAB_LABEL: Record<MainTab, string> = {
  analyze: "Analyze",
  history: "History",
  "api-key": "Gemini key",
  releases: "Releases",
  account: "Account",
};

type AppNavProps = {
  /** The tab this route *is*, or `null` on a route that is none of them. */
  activeTab: MainTab | null;
  /**
   * Supplied only by the route that already renders the tabs (`/app`). It swaps
   * the anchor's navigation for an in-place URL update so the shell is never
   * unmounted. Everywhere else the href *is* the navigation, which is why the
   * tabs are real links and not buttons.
   */
  onSelectTab?: (tab: MainTab) => void;
  /** True only on the landing page, where the brand link is the current page. */
  landing?: boolean;
  /** Draw the Account entry (auth phase 2): sign-in configured and the
   *  server's `auth` capability `ok`. From HomeScreen on `/app`, from
   *  `useAccountEntry` (via `RouteNav`) everywhere else. */
  showAccount?: boolean;
  /** Where the session stands, for the Account control: "loading" draws
   *  nothing in the bar (the phone menu row says "Account"), "signed-out" the
   *  "Sign in" pill, "signed-in" the round initial button. `/app` derives it
   *  in HomeScreen; every other route through `RouteNav`. */
  accountState?: AccountState;
  /** The signed-in person's initial for the Account button; null or absent
   *  draws the person glyph. */
  accountInitial?: string | null;
  /** The signed-out label of the Account entry (bar pill and phone-menu
   *  row). "Sign in" by default; the landing page, for new visitors, passes
   *  "Get 10 free runs" (2026-11-14). The dock keeps "Account". */
  signedOutLabel?: string;
  /** A shorter bar-pill label for the narrow end of the inline bar
   *  (48rem to 50rem), where a long `signedOutLabel` would run into the
   *  page gutter. The phone-menu row always uses `signedOutLabel`. */
  signedOutShortLabel?: string;
};

/** What the Account entry says, signed out, where it is a text label. */
const SIGN_IN_LABEL = "Sign in";

/** The ring-and-dot mark from the boards. Decorative: the word beside it is the
 *  name. Exported for the installed app's splash and Welcome (Phase 5d), which
 *  draw the same mark larger via their own class. */
export function BrandMark({ className = "brand-mark" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 26 26" aria-hidden="true" focusable="false">
      <circle className="brand-ring" cx="13" cy="13" r="11.25" fill="none" strokeWidth="2.25" />
      <circle className="brand-dot" cx="13" cy="13" r="5" />
    </svg>
  );
}

export default function AppNav({
  activeTab,
  onSelectTab,
  landing = false,
  showAccount = false,
  accountState = "loading",
  accountInitial = null,
  signedOutLabel = SIGN_IN_LABEL,
  signedOutShortLabel,
}: AppNavProps) {
  const signedOut = accountState === "signed-out";
  const tabs = navTabs(showAccount);
  /* Inline text tabs leave Account out: it is the round button instead. */
  const inlineTabs = tabs.filter((tab) => tab !== "account");
  const [menuOpen, setMenuOpen] = useState(false);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const closeMenu = useCallback(() => setMenuOpen(false), []);

  /* Escape closes the phone menu and hands focus back to the button that
     opened it — the menu replaced the content band, so there is nowhere else
     sensible for focus to land. */
  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      closeMenu();
      toggleRef.current?.focus();
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
    <>
      {/* `data-menu-open` lives on the bar because the toggle that drives it
          does; the stylesheet reads it through the sibling combinator to swap
          the views for `.menu-panel` below. */}
      <header className="nav-wrap" data-menu-open={menuOpen ? "true" : "false"}>
        <div className="nav">
          {/* Two copies of the brand, CSS shows one (Phase 5c). In a browser
              tab it is a link to the landing page at `/`. In the installed app
              there is no landing page — `/` redirects straight back to
              `/app` — so it stays a plain wordmark there rather than a link
              that reloads the screen you are on. `<html data-shell>` is
              stamped pre-paint, so neither flashes. */}
          <Link href="/" className="brand brand--link" aria-current={activeTab === null && landing ? "page" : undefined}>
            <BrandMark />
            videolens
          </Link>
          <span className="brand brand--static">
            <BrandMark />
            videolens
          </span>

          <div className="nav-actions">
            <nav className="nav-links" aria-label="Main">
              {inlineTabs.map((tab) => (
                <Link
                  key={tab}
                  className="nav-tab"
                  href={mainTabHref(tab)}
                  aria-current={activeTab === tab ? "page" : undefined}
                  onClick={handleTabClick(tab)}
                >
                  {TAB_LABEL[tab]}
                </Link>
              ))}
            </nav>

            <ThemeToggle />

            {/* Shown only where the inline tabs are (CSS, from 48rem). Same
                href and in-place switch as the text tab it replaces. Signed
                out it is a labelled pill, a call to action; signed in, the
                round initial. Nothing while the session loads: the bar is
                right-aligned, so a pill that turned into a circle (or the
                reverse) would jump the theme toggle and the tabs. */}
            {showAccount && signedOut && (
              <Link
                className="nav-account nav-account--signin"
                href={mainTabHref("account")}
                aria-current={activeTab === "account" ? "page" : undefined}
                onClick={handleTabClick("account")}
              >
                {signedOutShortLabel ? (
                  <>
                    <span className="nav-account__long">{signedOutLabel}</span>
                    <span className="nav-account__short">{signedOutShortLabel}</span>
                  </>
                ) : (
                  signedOutLabel
                )}
              </Link>
            )}
            {showAccount && accountState === "signed-in" && (
              <Link
                className="nav-account"
                href={mainTabHref("account")}
                aria-label={TAB_LABEL.account}
                title={TAB_LABEL.account}
                aria-current={activeTab === "account" ? "page" : undefined}
                onClick={handleTabClick("account")}
              >
                {accountInitial ? (
                  <span className="nav-account__initial" aria-hidden="true">
                    {accountInitial}
                  </span>
                ) : (
                  <UserRound aria-hidden="true" />
                )}
              </Link>
            )}

            <button
              ref={toggleRef}
              type="button"
              className="menu-toggle"
              onClick={() => setMenuOpen((open) => !open)}
              aria-expanded={menuOpen}
              aria-controls="site-menu"
              aria-label={menuOpen ? "Close menu" : "Menu"}
            >
              {menuOpen ? <X aria-hidden="true" /> : <Menu aria-hidden="true" />}
            </button>
          </div>
        </div>
      </header>

      {/* The phone menu. A sibling of the bar, not a child, so it sits in the
          shell's flex chain where the views do and is measured like them.
          Labelled "Main" like the inline links: below 48rem it is the main
          navigation, and the two are never on screen together. */}
      <nav id="site-menu" className="menu-panel" aria-label="Main">
        {tabs.map((tab) => (
          <Link
            key={tab}
            className="menu-item"
            href={mainTabHref(tab)}
            aria-current={activeTab === tab ? "page" : undefined}
            onClick={handleTabClick(tab)}
          >
            {tab === "account" && signedOut ? signedOutLabel : TAB_LABEL[tab]}
            <ChevronRight aria-hidden="true" />
          </Link>
        ))}
      </nav>
    </>
  );
}
