"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { AccountResponse } from "@/domain/entities";
import { ApiError, NetworkError } from "@/domain/errors";
import { classifyGatewayError } from "@/application/gatewayError";
import { signOut } from "@/application/useAuthSession";
import { useRestoredEpoch } from "@/application/accountHold";
import { accountGateway } from "@/infrastructure/container";

/** How `/api/me` went, in the terms the Account panel draws:
 *  - `unavailable`: 503, the server has no sign-in configured. Calm, not red.
 *  - `rejected`: 401, this server did not accept the session (a token from a
 *    different project, or one revoked since). Offer to sign out.
 *  - `held`: 410 `account_pending_deletion` (2026-11-14): the account is in
 *    the 30-day deletion hold and can be restored until `purgeAt`.
 *  - `failed`: anything else; retry. */
export type AccountProblem =
  | { kind: "unavailable" }
  | { kind: "rejected" }
  | { kind: "held"; purgeAt: string | null }
  | { kind: "failed"; message: string };

type Loaded = { userId: string; epoch: number; account: AccountResponse | null; problem: AccountProblem | null };

const FALLBACK = "Your account could not be loaded.";

/**
 * `GET /api/me` for the signed-in person (auth phase 2). Nothing is fetched
 * while signed out: the endpoint needs a credential and answers 401 without
 * one. `userId` is the dependency that refetches, so a sign-in, a sign-out
 * or a different person in another tab each get their own answer.
 *
 * The result is keyed by the user it was fetched for and derived during
 * render, so a stale answer for the previous person is never shown and no
 * effect has to reset state on the way in. No billing: the paid tier is
 * deferred, so the branch's `upgrade`/`manageBilling` are not lifted.
 */
export function useAccount(userId: string | null) {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [attempt, setAttempt] = useState(0);
  /* A restore lifts the hold: read the account again. */
  const restoredEpoch = useRestoredEpoch();

  useEffect(() => {
    if (!userId) return;
    let cancelled = false;
    accountGateway
      .fetchAccount()
      .then((account) => {
        if (!cancelled) setLoaded({ userId, epoch: restoredEpoch, account, problem: null });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const status = err instanceof ApiError ? err.status : undefined;
        const problem: AccountProblem =
          status === 503
            ? { kind: "unavailable" }
            : status === 401
              ? { kind: "rejected" }
              : err instanceof ApiError && err.code === "account_pending_deletion"
                ? { kind: "held", purgeAt: err.purgeAt ?? null }
                : { kind: "failed", message: classifyGatewayError(err, FALLBACK).message };
        setLoaded({ userId, epoch: restoredEpoch, account: null, problem });
      });
    return () => {
      cancelled = true;
    };
  }, [userId, attempt, restoredEpoch]);

  const reload = useCallback(() => {
    setLoaded(null);
    setAttempt((n) => n + 1);
  }, []);

  /* An answer from before the last restore is stale (it may be the 410). */
  const current =
    userId && loaded?.userId === userId && loaded.epoch === restoredEpoch ? loaded : null;
  return {
    account: current?.account ?? null,
    problem: current?.problem ?? null,
    loading: userId !== null && current === null,
    reload,
  };
}

/** Why `DELETE /api/me` did not go through, in the panel's terms:
 *  - `rejected`: 401, the server did not accept the sign-in.
 *  - `unavailable`: 503, this server's account store is off.
 *  - `unreachable`: no answer at all (or the sign-in could not be confirmed).
 *  - `failed`: anything else, including 403 (an API-key caller, which the
 *    panel never is) and a 404/405 from a server without the route yet. */
export type DeletionProblem = "rejected" | "unavailable" | "unreachable" | "subscription" | "failed";

export type DeletionState =
  | { phase: "idle" }
  | { phase: "deleting" }
  | { phase: "failed"; problem: DeletionProblem; message: string };

const DELETION_MESSAGE: Record<DeletionProblem, string> = {
  /* Also the answer to a retry whose 204 was lost: the account is already
     gone, so this must not claim that nothing was deleted. */
  rejected:
    "This server did not accept your sign-in. If you already deleted your account, it is gone. If not, sign out, sign in again and try once more.",
  unavailable: "Deleting accounts is not available on this server. Nothing was deleted.",
  unreachable:
    "Could not reach VideoLens to delete your account. Check your connection and try again.",
  /* 503 `subscription_cancel_failed` (paid plan, 2026-11-13): deletion
     cancels the subscription first, and that step failed, so nothing was
     deleted and nothing about the plan changed. The form stays usable. */
  subscription:
    "We couldn’t cancel your subscription, so your account was not deleted. Your account and subscription are unchanged. Try again in a moment.",
  failed: "Your account could not be deleted just now. Try again in a moment.",
};

function deletionProblem(err: unknown): DeletionProblem {
  if (err instanceof NetworkError) return "unreachable";
  if (err instanceof ApiError && err.status === 401) return "rejected";
  if (err instanceof ApiError && err.code === "subscription_cancel_failed") return "subscription";
  if (err instanceof ApiError && err.status === 503) return "unavailable";
  return "failed";
}

/**
 * `DELETE /api/me` for the signed-in person (auth phase 3; the 30-day hold
 * since 2026-11-14: a 200 with `purge_at`, handed on as `purgeAt`; an older
 * backend's 204 removed the account at once and hands on null).
 *
 * On success it starts `AuthSession.signOut()` and hands the settling promise to
 * `onDeleted` at once, so the panel swaps to its "deleted" card immediately
 * but can hold "Back to sign in" until the stored session is really gone.
 * (supabase-js awaits a `/logout` request before clearing it; a signed-in
 * view mounted earlier would call `GET /api/me` with the old token.)
 * Signing out is the whole cleanup: the stored Supabase session is the only
 * auth state this app keeps in the browser.
 * History (IndexedDB) and the BYOK key (localStorage) are the person's own
 * data and are left alone, so nothing here calls `localStorage.clear()`.
 *
 * Whether to allow the call (the typed email, the run guard) is the panel's
 * decision; this hook only refuses a second call while one is in flight.
 */
export function useAccountDeletion(onDeleted: (signedOut: Promise<void>, purgeAt: string | null) => void) {
  const [state, setState] = useState<DeletionState>({ phase: "idle" });
  const inFlight = useRef(false);

  const remove = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    setState({ phase: "deleting" });
    let purgeAt: string | null = null;
    try {
      ({ purgeAt } = await accountGateway.deleteAccount());
    } catch (err: unknown) {
      /* A retry whose 200 was lost: the account is already held, which is
         exactly what was asked for. */
      if (err instanceof ApiError && err.code === "account_pending_deletion") {
        purgeAt = err.purgeAt ?? null;
      } else {
        inFlight.current = false;
        const problem = deletionProblem(err);
        setState({ phase: "failed", problem, message: DELETION_MESSAGE[problem] });
        return;
      }
    }
    /* The account stops working whatever happens next; `signOut` removes
       the stored session by hand even when the provider call fails. */
    const signedOut = signOut().catch(() => undefined);
    onDeleted(signedOut, purgeAt);
    await signedOut;
    inFlight.current = false;
  }, [onDeleted]);

  const reset = useCallback(() => {
    if (!inFlight.current) setState({ phase: "idle" });
  }, []);

  return { state, remove, reset };
}
