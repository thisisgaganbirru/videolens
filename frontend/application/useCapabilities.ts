"use client";

import { useEffect, useState } from "react";
import type { Capability, CapabilityReport } from "@/domain/entities";
import { capabilitiesGateway } from "@/infrastructure/container";

/* What the deployment says about itself, so a user learns a source will not
   work *before* spending an upload on it rather than after waiting through a
   run that was never going to succeed.

   Three policy decisions live here rather than in the adapter or the
   components, because all three are orchestration:

   1. **Failure is silent.** The adapter throws like every other gateway — it
      is not its job to decide that a failure does not matter. This hook
      swallows it and leaves `report` at `null`. Missing health information is
      not itself a health problem, and a banner saying "could not check whether
      the service is healthy" is pure noise on a service that is, in fact,
      fine. The one thing it must never do is block or replace the app.
   2. **One fetch, on mount.** No polling. The backend caches for 10s, but the
      reason not to poll is not cost: a capability report is deployment shape,
      which changes on a redeploy, not between two clicks. The single caller is
      `HomeScreen`, which is never unmounted by a tab switch (the tabs are a
      `pushState` query param), so this is one request per app load — not one
      per tab visit. That is also why the two contextual notices take props
      from `HomeScreen` instead of calling this hook themselves.
   3. **Only `degraded` and `unavailable` are worth showing.** `ok` shows
      nothing — a permanent "all systems operational" strip is chrome that
      tells the user nothing they can act on. `disabled` shows nothing either,
      and this is the load-bearing part: `disabled` is deployment shape, not a
      fault (object storage unconfigured in local dev is normal), and the
      backend already excludes it from the overall state. Re-deriving severity
      here would be the obvious place to accidentally put it back. */

/** The states that mean "tell the user". Anything else — `ok`, `disabled`, or
 *  a state string this build has never heard of — is silent. Alarming about a
 *  value we cannot interpret would be guessing. */
const NOTICEABLE = new Set(["degraded", "unavailable"]);

export function isNoticeable(state: string): boolean {
  return NOTICEABLE.has(state);
}

function find(report: CapabilityReport | null, name: string): Capability | null {
  return report?.capabilities.find((row) => row.name === name) ?? null;
}

export function useCapabilities() {
  const [report, setReport] = useState<CapabilityReport | null>(null);

  useEffect(() => {
    let cancelled = false;
    capabilitiesGateway
      .fetchReport()
      .then((next) => {
        if (!cancelled) setReport(next);
      })
      .catch(() => {
        /* Deliberately empty — see (1) above. */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return {
    /** The whole report, or `null` when it has not arrived or never will. */
    report,
    /** The report *only when it is worth surfacing*. `null` covers healthy,
     *  not-yet-loaded and never-loaded alike, so a component can render this
     *  without re-deciding what counts as a problem. */
    notice: report && isNoticeable(report.state) ? report : null,
    /** Wired to the URL field: degraded here means URL runs may fail. */
    urlDownload: find(report, "url_download"),
    /** Wired to the API-key panel: unavailable here means the shared budget is
     *  spent and a bring-your-own key is the way through. */
    dailyBudget: find(report, "daily_budget"),
  };
}
