"use client";

import type { MouseEvent } from "react";
import Link from "next/link";
import { ChevronLeft } from "lucide-react";
import { isPlainLeftClick } from "@/components/navClick";
import { hasInAppPrevious } from "@/application/backNavigation";
import { goToMainTab, isAppPath, mainTabHref } from "@/application/useMainTab";

/* Hallmark · theme: editorial · component: back link (app shell; every shell on Privacy/Terms)
 * states: default · hover · focus-visible · active · hidden (web shell, unless `everywhere`)
 *
 * A quiet "‹ Back" above the title of API key, Releases, Privacy and Terms.
 * Those four open from the More sheet, and an installed app on iOS has no
 * browser back button, so without this the only way out is the dock.
 *
 * Rendered on every shell and hidden by CSS unless `<html data-shell="app">`
 * — the attribute is stamped before first paint, so there is no flash, and
 * `display: none` keeps it out of the tab order and the accessibility tree in
 * the web shell, where the browser has its own back. Privacy and Terms opt
 * out of that with `everywhere` (refinement 10), so they show it on the web
 * too; there the target is `/app`, and in the installed app a cold-open Back
 * still lands on `/app.html` through canonicalizeAppPath (refinement 9).
 *
 * A real link to Analyze (`/app`), so middle-click and "copy link" still mean
 * something. A plain left-click is intercepted: back through history when the
 * previous entry is part of the app (the view the user came from), otherwise
 * Analyze — in place on `/app`, where the views are a query param, and as an
 * ordinary navigation from the legal routes. */
type AppBackLinkProps = {
  /** Refinement 10 (owner): Privacy and Terms show it in every shell, the web
   *  included — a reader who opened a legal page from the footer wants a way
   *  back to the tool that does not depend on the browser. API key and
   *  Releases keep it app-only: on the web they are tabs in the nav. */
  everywhere?: boolean;
};

export default function AppBackLink({ everywhere = false }: AppBackLinkProps) {
  const handleClick = (event: MouseEvent<HTMLAnchorElement>) => {
    if (!isPlainLeftClick(event)) return;
    if (hasInAppPrevious()) {
      event.preventDefault();
      window.history.back();
      return;
    }
    if (isAppPath(window.location.pathname)) {
      event.preventDefault();
      goToMainTab("analyze");
    }
    /* Otherwise (a legal route opened cold): let the link navigate to `/app`. */
  };

  return (
    <Link href={mainTabHref("analyze")} prefetch={false} className={everywhere ? "app-back app-back--everywhere" : "app-back"} onClick={handleClick}>
      <ChevronLeft aria-hidden="true" />
      Back
    </Link>
  );
}
