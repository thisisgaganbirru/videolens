"use client";

import type { MouseEvent } from "react";
import Link from "next/link";
import { ChevronLeft } from "lucide-react";
import { isPlainLeftClick } from "@/components/navClick";
import { hasInAppPrevious } from "@/application/backNavigation";
import { goToMainTab, mainTabHref } from "@/application/useMainTab";

/* Hallmark · theme: editorial · component: back link (installed-app shell only)
 * states: default · hover · focus-visible · active · hidden (web shell)
 *
 * A quiet "‹ Back" above the title of API key, Releases, Privacy and Terms.
 * Those four open from the More sheet, and an installed app on iOS has no
 * browser back button, so without this the only way out is the dock.
 *
 * Rendered on every shell and hidden by CSS unless `<html data-shell="app">`
 * — the attribute is stamped before first paint, so there is no flash, and
 * `display: none` keeps it out of the tab order and the accessibility tree in
 * the web shell, where the browser has its own back.
 *
 * A real link to Analyze (`/`), so middle-click and "copy link" still mean
 * something. A plain left-click is intercepted: back through history when the
 * previous entry is part of the app (the view the user came from), otherwise
 * Analyze — in place on `/`, where the views are a query param, and as an
 * ordinary navigation from the legal routes. */
export default function AppBackLink() {
  const handleClick = (event: MouseEvent<HTMLAnchorElement>) => {
    if (!isPlainLeftClick(event)) return;
    if (hasInAppPrevious()) {
      event.preventDefault();
      window.history.back();
      return;
    }
    if (window.location.pathname === "/") {
      event.preventDefault();
      goToMainTab("analyze");
    }
    /* Otherwise (a legal route opened cold): let the link navigate to `/`. */
  };

  return (
    <Link href={mainTabHref("analyze")} prefetch={false} className="app-back" onClick={handleClick}>
      <ChevronLeft aria-hidden="true" />
      Back
    </Link>
  );
}
