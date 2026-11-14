"use client";

import { useEffect, useState } from "react";
import type { AuthUser, Capability } from "@/domain/entities";
import { authSession, capabilitiesGateway } from "@/infrastructure/container";
import { useAuthUser } from "@/application/useAuthSession";

/* The Account entry in the shared chrome (top bar control, phone-menu row,
   dock item) on every route, not only `/app` (owner, 2026-11-14). See
   docs/frontend/auth-sign-in.md, "Sign in call to action".

   One gate everywhere: a provider configured in this build *and* the
   server's `auth` capability `ok`. `/app` already reads both (useAuthUser +
   useCapabilities in HomeScreen) and derives the entry with `accountEntryFrom`
   below. The other routes have no shell that reads capabilities, so
   `useAccountEntry` reads the `auth` row itself, once per page load, shared
   by the nav and the dock (both call the hook; one request). */

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

let authCapabilityRead: Promise<Capability | null> | null = null;

/** The `auth` capability row, read once per page load. A failed read is
 *  forgotten so a later mount can try again, and counts as "no" meanwhile:
 *  missing health information hides the entry, it never shows a broken one. */
function readAuthCapability(): Promise<Capability | null> {
  if (!authCapabilityRead) {
    authCapabilityRead = capabilitiesGateway
      .fetchReport()
      .then((report) => report.capabilities.find((row) => row.name === "auth") ?? null)
      .catch(() => {
        authCapabilityRead = null;
        return null;
      });
  }
  return authCapabilityRead;
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
    void readAuthCapability().then((row) => {
      if (!cancelled) setAuthCapability(row);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return accountEntryFrom(auth, authCapability);
}
