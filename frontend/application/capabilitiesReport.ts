import type { CapabilityReport } from "@/domain/entities";
import { capabilitiesGateway } from "@/infrastructure/container";
import { noteReadResult } from "@/application/serverReachability";

/* The one `GET /api/capabilities` read the screens share (2026-11-26,
   Android QA run 25b). `/app` (useCapabilities, in HomeScreen) and every
   other route (useAccountEntry: nav, dock, landing hint) used to read it
   separately, and neither read it again when the network came back: after
   an offline launch the Account tab and the "Sign in for 10 a day" hint
   stayed missing until the app was left and reopened.

   - Read until a report arrives, then stop. A report is deployment shape
     (useCapabilities, decision 2), so a healthy launch is one request and a
     healthy app toggling Wi-Fi makes none.
   - The `online` event retries a read that never arrived, ungated by
     `navigator.onLine` (the WebView can fire `online` before it reads true),
     on every route. It is one retry per event, not a loop: if the network is
     not usable yet when it fires, `/app` still has serverReachability's
     focus/visibility chances, and the next `online` tries again.
   - Every report counts, whoever asked for it (the transport re-reads while
     sign-in is unconfirmed): `subscribe` hears them all.

   Application layer: it orchestrates the gateway and reports reachability;
   the adapter still only fetches and normalises. */

let latest: CapabilityReport | null = null;
let reading: Promise<void> | null = null;
let watching = false;

function hear(report: CapabilityReport) {
  latest = report;
  noteReadResult("capabilities");
}

function watch() {
  if (watching) return;
  watching = true;
  /* Page-lifetime, like the gateway itself: these never need removing. */
  capabilitiesGateway.subscribe(hear);
  window.addEventListener("online", () => {
    void loadCapabilities();
  });
}

/** The latest report this page load has seen, or `null` before one arrives. */
export function latestCapabilities(): CapabilityReport | null {
  return latest;
}

/** Read the report unless one has arrived; a read already in flight is
 *  shared. Resolves when the read answers, so a caller can tell "settled"
 *  (a failure counts). A failure is reported to serverReachability and
 *  otherwise swallowed: missing health information never blocks the app.
 *  Client only: call it from an effect. */
export function loadCapabilities(): Promise<void> {
  watch();
  if (latest) return Promise.resolve();
  if (!reading) {
    reading = capabilitiesGateway
      .fetchReport()
      .then(
        () => undefined,
        (err: unknown) => {
          noteReadResult("capabilities", err);
        }
      )
      .finally(() => {
        reading = null;
      });
  }
  return reading;
}

/** Hear every report from now on. Returns the unsubscribe. */
export function onCapabilities(listener: (report: CapabilityReport) => void): () => void {
  watch();
  return capabilitiesGateway.subscribe(listener);
}
