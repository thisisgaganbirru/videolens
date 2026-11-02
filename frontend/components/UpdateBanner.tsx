"use client";

import { Download, X } from "lucide-react";
import { useUpdateCheck } from "@/application/useUpdateCheck";

/* Hallmark · component: banner · genre: editorial · theme: custom (app/tokens.css)
 * states: hidden · shown · link hover · link focus-visible · link active ·
 *         dismiss hover · dismiss focus-visible · dismiss active · dismissed
 * contrast: ink on surface 17.6:1 light / 15.4:1 dark; ink-2 on surface ≥ 11:1.
 *
 * Refinement 9: restyled into the editorial system. It was the Terminal-era
 * band (12.5px copy beside a 16px lowercase "download update"), with no way to
 * put it away. Now: the free-runs strip's type (15px, ink headline + ink-2
 * line), a sentence-case near-black "Get the update" pill, and a dismiss that
 * remembers this build only (useUpdateCheck; a newer build shows again).
 *
 * Native Android only (the check no-ops elsewhere). It sits directly inside
 * .viewport, above the shell, so it carries `flex-shrink: 0` (.update-banner):
 * a shrinking banner would leave the measured one-viewport frame below it the
 * wrong height. Sideways on a phone it drops to one 44px row (globals.css).
 *
 * The link keeps `target="_blank"`: in the Capacitor WebView that hands the
 * release page to the system browser (Chrome) instead of opening it inside
 * the app, which is what makes the APK download and install prompt work. */

export default function UpdateBanner() {
  const { update, dismiss } = useUpdateCheck();

  if (!update) return null;

  return (
    <aside className="update-banner" aria-label="App update" style={{ zIndex: "var(--z-banner)" }}>
      <p className="update-banner__text">
        <strong>Update available.</strong> <span>Version {update.versionName} is ready to install.</span>
      </p>
      <a href={update.releaseUrl} target="_blank" rel="noopener noreferrer" className="btn btn-ink btn-pill update-banner__action">
        <Download aria-hidden="true" />
        Get the update
      </a>
      <button type="button" className="update-banner__dismiss" onClick={dismiss} aria-label="Dismiss the update notice">
        <X aria-hidden="true" />
      </button>
    </aside>
  );
}
