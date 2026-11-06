"use client";

import type { MouseEvent } from "react";
import { goToMainTab, mainTabHref } from "@/application/useMainTab";
import { isPlainLeftClick } from "@/components/navClick";

/* Hallmark · component: inline notice · genre: editorial · theme: custom (app/tokens.css)
 * states: hidden · offline · unreachable · link hover · focus-visible · active
 * contrast: ink on surface 17.6:1 light / 15.4:1 dark; the dot is neutral
 *           (--color-muted), decorative — the sentence carries the state.
 *
 * Refinement 4 (LCH-06): Analyze says when the server cannot be reached,
 * before anyone submits. The capability notice's own card (.cap-notice, one
 * line, neutral dot), because it is the same kind of fact — the deployment's
 * state, not a failure of something the user did — and two different boxes
 * for "the server is limited" and "the server is not there" would read as two
 * systems. Never red: nothing has gone wrong yet, nothing is blocked (the form
 * stays usable, and a submit still gets its own error), and History works
 * offline, which is the one useful thing to say.
 *
 * The live region is the always-present slot in HomeScreen, so it is
 * announced when it appears and when it goes. */

function openHistory(event: MouseEvent<HTMLAnchorElement>) {
  if (!isPlainLeftClick(event)) return;
  event.preventDefault();
  goToMainTab("history");
}

export default function ReachabilityNotice({ state }: { state: "offline" | "unreachable" }) {
  return (
    <div className="cap-notice reach-notice" data-state={state}>
      <div className="cap-head">
        <span className="cap-dot" aria-hidden="true" />
        <p className="cap-summary-text">
          {state === "offline" ? "You're offline right now." : "Can't reach the server right now."} You can
          still open past runs in History.
        </p>
        <a className="cap-toggle" href={mainTabHref("history")} onClick={openHistory}>
          History
        </a>
      </div>
    </div>
  );
}
