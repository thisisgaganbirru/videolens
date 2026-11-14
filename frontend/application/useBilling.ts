"use client";

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import type { BillingDetails, BillingInterval, BillingStatus } from "@/domain/entities";
import { ApiError } from "@/domain/errors";
import { classifyGatewayError } from "@/application/gatewayError";
import { takeSearchParam } from "@/application/useMainTab";
import { revalidateFreeRuns } from "@/application/useFreeRuns";
import { billingGateway, nativeShell } from "@/infrastructure/container";

/* The paid plan (2026-11-13, "Level 3, one paid plan"): Stripe-hosted
   Checkout and Customer Portal, reached by a top-level redirect. No Stripe.js
   and no card data in this app. See docs/frontend/billing.md.

   One copy of the signed-in account's plan, outside React like the free-run
   count, because the Account panel (the Plan group), the Analyze strip (the
   extra-run price) and the upload limits (the paid tier) all read it, and
   HomeScreen, which never unmounts, is the one place that knows who is
   signed in and whether the server sells a plan at all.

   Quiet by design, like the other launch reads. Nothing is fetched unless
   the server's `billing` capability is `ok` and someone is signed in, so a
   server with billing off (or without it) sees no request and the app looks
   exactly as before. A failed read hides the Plan group rather than guessing;
   a later read (tab visible again, app resumed) can bring it back.

   Returning from Checkout (`/app?view=account&billing=success|cancel`): the
   param is read once and stripped, then for success the plan is re-read with
   backoff for about 20 s, because Stripe's webhook can land a few seconds
   after the redirect. */

/** What the Account panel says after a checkout redirect comes back. */
export type CheckoutReturn = "confirming" | "paid" | "cancelled" | "unconfirmed";

type Snapshot = {
  /** Whose plan `status` is: the signed-in user id, or null when nothing is
   *  being read (signed out, or the server sells no plan). */
  owner: string | null;
  status: BillingStatus | null;
  notice: CheckoutReturn | null;
};

let snapshot: Snapshot = { owner: null, status: null, notice: null };
const listeners = new Set<() => void>();
let owner: string | null = null;
let epoch = 0;
let inFlight: Promise<BillingStatus | null> | null = null;
let returnTaken = false;

function publish(next: Partial<Snapshot>) {
  snapshot = { ...snapshot, ...next };
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function isPaid(status: BillingStatus | null): boolean {
  return status !== null && status.enabled && status.plan === "paid";
}

/** Re-read the plan for whoever is signed in. Shares an in-flight request;
 *  resolves null when nothing is read or the read failed, never rejects. */
export function refreshBilling(): Promise<BillingStatus | null> {
  if (!owner) return Promise.resolve(null);
  if (inFlight) return inFlight;
  const asked = epoch;
  const request: Promise<BillingStatus | null> = billingGateway.fetchBilling().then(
    (status): BillingStatus | null | Promise<BillingStatus | null> => {
      inFlight = null;
      if (asked !== epoch) return refreshBilling();
      const confirmed = isPaid(status) && (snapshot.notice === "confirming" || snapshot.notice === "unconfirmed");
      publish({ owner, status, ...(confirmed ? { notice: "paid" as const } : {}) });
      return status;
    },
    (): null | Promise<BillingStatus | null> => {
      inFlight = null;
      if (asked !== epoch) return refreshBilling();
      /* Keep a plan already shown (a blip should not make it vanish); with
         none yet, the group simply stays hidden. */
      return null;
    }
  );
  inFlight = request;
  return request;
}

function setOwner(next: string | null): void {
  if (next === owner) return;
  owner = next;
  epoch += 1;
  inFlight = null;
  publish({ owner: next, status: null });
  if (next) void refreshBilling();
}

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));
/* Waits between reads after a successful checkout: 0 + 1.5 + 2.5 + 4 + 5 + 7
   = 20 s in all, quick first and slower after. */
const CONFIRM_DELAYS_MS = [0, 1500, 2500, 4000, 5000, 7000];

async function confirmPayment(): Promise<void> {
  for (const delay of CONFIRM_DELAYS_MS) {
    await sleep(delay);
    if (snapshot.notice !== "confirming") return;
    if (isPaid(await refreshBilling())) break;
  }
  /* The free-run strip and the upload limits follow the plan. */
  void revalidateFreeRuns();
  if (snapshot.notice === "confirming") publish({ notice: isPaid(snapshot.status) ? "paid" : "unconfirmed" });
}

/** Once per app load: the `billing` param a Checkout redirect came back
 *  with, removed from the address so a reload does not repeat it. */
function takeCheckoutReturn(): void {
  if (returnTaken) return;
  returnTaken = true;
  const value = takeSearchParam("billing");
  if (value === "cancel") {
    publish({ notice: "cancelled" });
  } else if (value === "success") {
    publish({ notice: "confirming" });
    void confirmPayment();
  }
}

/**
 * The signed-in account's plan, for the shell. `userId` is who is signed in
 * (null for nobody or not known yet); `enabled` is whether the server sells a
 * plan (its `billing` capability is `ok`). Either changing re-reads.
 *
 * Call once, from the always-mounted shell (`HomeScreen`).
 */
export function useBilling(userId: string | null, enabled: boolean) {
  const current = useSyncExternalStore(subscribe, () => snapshot, () => snapshot);
  const active = enabled && userId !== null;

  useEffect(() => {
    takeCheckoutReturn();
  }, []);

  useEffect(() => {
    setOwner(active ? userId : null);
  }, [active, userId]);

  /* Back from the Stripe page in another tab, or, in the installed app,
     from the system browser checkout opened in: read the plan again. */
  useEffect(() => {
    if (!active) return;
    let last = 0;
    const again = () => {
      const now = Date.now();
      if (now - last < 1500) return;
      last = now;
      void refreshBilling();
    };
    const onVisible = () => {
      if (document.visibilityState === "visible") again();
    };
    document.addEventListener("visibilitychange", onVisible);
    const offResume = nativeShell.onResume(again);
    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      offResume();
    };
  }, [active]);

  const status = active && current.owner === userId ? current.status : null;
  return {
    /** `{enabled: true, ...}` only once read; null while unknown, signed
     *  out, failed, or when the server sells no plan. */
    billing: (status && status.enabled ? status : null) as BillingDetails | null,
    /** The checkout-return notice, if this load came back from Checkout. */
    notice: current.notice,
  };
}

export type BillingAction = BillingInterval | "portal";

const ACTION_FALLBACK: Record<BillingAction, string> = {
  month: "Checkout could not start just now. Try again in a moment.",
  year: "Checkout could not start just now. Try again in a moment.",
  portal: "Billing could not open just now. Try again in a moment.",
};

/**
 * The two ways off to Stripe: Checkout (`month`/`year`) and the Customer
 * Portal. Asks the server for the page's address, then navigates the whole
 * window there with `location.assign`.
 *
 * In the installed app that same call hands the address to the system
 * browser: Capacitor's WebView opens any host that is not the app's own
 * with an ACTION_VIEW intent (the path `target="_blank"` links already take,
 * see UpdatePrompt) and stays where it is. So no extra plugin is needed;
 * `handedOff` tells the panel to say where checkout went, and the plan is
 * re-read when the app comes back to the front (`useBilling`).
 */
export function useBillingActions() {
  const [busy, setBusy] = useState<BillingAction | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [handedOff, setHandedOff] = useState(false);
  const busyRef = useRef(false);

  /* Back from Stripe through the browser's back button can restore this page
     from the back/forward cache with the button still "Opening…". */
  useEffect(() => {
    const onShow = (event: PageTransitionEvent) => {
      if (!event.persisted) return;
      busyRef.current = false;
      setBusy(null);
      void refreshBilling();
    };
    window.addEventListener("pageshow", onShow);
    return () => window.removeEventListener("pageshow", onShow);
  }, []);

  const run = useCallback(async (action: BillingAction) => {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(action);
    setError(null);
    let url: string;
    try {
      url =
        action === "portal" ? await billingGateway.openPortal() : await billingGateway.startCheckout(action);
    } catch (err: unknown) {
      busyRef.current = false;
      setBusy(null);
      const code = err instanceof ApiError ? err.code : undefined;
      if (code === "already_subscribed") {
        setError("You are already on the paid plan.");
        void refreshBilling();
      } else if (
        code === "invalid_interval" ||
        code === "billing_disabled" ||
        code === "billing_unavailable"
      ) {
        /* 400 invalid_interval, 503 billing_disabled / billing_unavailable:
           nothing the person can fix here. */
        setError("Billing is unavailable right now. Try again later.");
      } else if (code === "no_billing_account") {
        setError("There is no billing account for you yet. It is set up at your first checkout.");
        void refreshBilling();
      } else {
        setError(classifyGatewayError(err, ACTION_FALLBACK[action]).message);
      }
      return;
    }
    const native = nativeShell.isNative();
    window.location.assign(url);
    if (native) {
      /* The app stays on screen; the page opened in the browser. */
      busyRef.current = false;
      setBusy(null);
      setHandedOff(true);
    }
  }, []);

  return { busy, error, handedOff, run };
}
