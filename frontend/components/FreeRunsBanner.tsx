"use client";

import type { MouseEvent } from "react";
import type { FreeRunsBanner as FreeRunsBannerState } from "@/application/useFreeRuns";
import { goToMainTab, mainTabHref } from "@/application/useMainTab";
import { isPlainLeftClick } from "@/components/navClick";

/* Hallmark · component: banner · genre: editorial · theme: custom (app/tokens.css)
 * boards: design/shots/IntakeFreeApp.png (runs left), IntakeLimitApp.png (spent)
 * states: hidden · runs left (plural / singular) · spent · link hover · focus-visible · active
 * contrast: ink on surface 17.6:1 light / 15.4:1 dark; danger-border is a
 *           decorative outline only — the words carry the state, not the red.
 *
 * The free-run allowance, above the intake's eyebrow on every shell (installed
 * app, phone web, desktop web). One white strip, the sentence on the left and
 * the near-black "Add key" pill on the right; the spent state swaps the
 * sentence and gives the strip a red hairline. Nothing else turns red — the
 * blocked Analyze button greys out (UploadForm), it does not shout.
 *
 * "Add key" is a link, not a button: it goes somewhere (the API key view,
 * `/app?view=api-key`), so it keeps a real href for middle-click and new-tab, and
 * switches tabs in place on a plain click like every other tab link.
 *
 * The live region is the always-present wrapper in HomeScreen, not this
 * component: a region that appears with its content announces nothing. */

function openApiKey(event: MouseEvent<HTMLAnchorElement>) {
  if (!isPlainLeftClick(event)) return;
  event.preventDefault();
  goToMainTab("api-key");
}

export default function FreeRunsBanner({ banner }: { banner: FreeRunsBannerState }) {
  const { remaining, exhausted } = banner;
  return (
    <div className="free-runs" data-state={exhausted ? "spent" : "left"}>
      <p className="free-runs__text">
        {exhausted ? (
          <>
            <strong>You have used your free runs.</strong> Add your own key to keep going.
          </>
        ) : (
          <>
            <strong>
              {remaining} free {remaining === 1 ? "run" : "runs"} left.
            </strong>{" "}
            Add your own key for more.
          </>
        )}
      </p>
      <a className="btn btn-ink btn-pill free-runs__action" href={mainTabHref("api-key")} onClick={openApiKey}>
        Add key
      </a>
    </div>
  );
}
