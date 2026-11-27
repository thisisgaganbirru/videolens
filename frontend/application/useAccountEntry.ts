"use client";

import { useEffect, useState } from "react";
import type { AuthUser, Capability, CapabilityReport } from "@/domain/entities";
import { authSession } from "@/infrastructure/container";
import { latestCapabilities, loadCapabilities, onCapabilities } from "@/application/capabilitiesReport";
import { useAuthUser } from "@/application/useAuthSession";

/* The Account entry in the shared chrome (top bar control, phone-menu row,
   dock item) on every route, not only `/app` (owner, 2026-11-14). See
   docs/frontend/auth-sign-in.md, "Sign in call to action".

   One gate everywhere: a provider configured in this build *and* the
   server's `auth` capability `ok`. `/app` already reads both (useAuthUser +
   useCapabilities in HomeScreen) and derives the entry with `accountEntryFrom`
   below. The other routes have no shell that reads capabilities, so
   `useAccountEntry` reads the `auth` row itself through the same shared
   read as `/app` (capabilitiesReport.ts): one request for nav, dock and
   landing hint, read again on `online` until a report arrives. */

export type AccountState = "loading" | "signed-out" | "signed-in";

export type AccountEntry = {
  /** Draw the Account entry at all. */
  showAccount: boolean;
  /** "loading" until the session is known: the bar draws nothing. */
  accountState: AccountState;
  /** The signed-in email's first character, uppercased; null otherwise. */
  accountInitial: string | null;
};

/** The entry from the two reads. Pure, so `/app` and every other route
 *  derive it the same way. */
export function accountEntryFrom(
  auth: { enabled: boolean; ready: boolean; user: AuthUser | null },
  authCapability: Capability | null
): AccountEntry {
  return {
    showAccount: auth.enabled && authCapability?.state === "ok",
    accountState: !auth.ready ? "loading" : auth.user ? "signed-in" : "signed-out",
    accountInitial: auth.user?.email?.trim().charAt(0).toUpperCase() || null,
  };
}

function authRow(report: CapabilityReport | null): Capability | null {
  return report?.capabilities.find((row) => row.name === "auth") ?? null;
}

/**
 * The Account entry for a route that is not `/app`. Renders nothing on the
 * server and on the first client render (capability null, session not
 * ready), so the prerendered HTML matches and the entry appears only once
 * both reads have answered. With no provider in this build nothing is
 * requested at all.
 */
export function useAccountEntry(): AccountEntry {
  const auth = useAuthUser();
  const [authCapability, setAuthCapability] = useState<Capability | null>(null);

  useEffect(() => {
    if (!authSession.enabled) return;
    let cancelled = false;
    /* Every report replaces the last: this read, a re-read the transport
       asked for while sign-in was unconfirmed (2026-11-21), or the retry on
       `online` after an offline load (2026-11-26, Android QA run 25b). */
    const stop = onCapabilities((report) => {
      if (!cancelled) setAuthCapability(authRow(report));
    });
    /* One shared read (capabilitiesReport.ts) for nav, dock and the landing
       hint, retried on `online` until a report arrives. A failure hides the
       entry; it never shows a broken one. A report this page load already
       has (a client navigation from `/app`) resolves at once and is used. */
    void loadCapabilities().then(() => {
      const seen = latestCapabilities();
      if (seen && !cancelled) setAuthCapability(authRow(seen));
    });
    return () => {
      cancelled = true;
      stop();
    };
  }, []);

  return accountEntryFrom(auth, authCapability);
}
