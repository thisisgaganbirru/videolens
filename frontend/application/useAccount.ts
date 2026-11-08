"use client";

import { useCallback, useEffect, useState } from "react";
import type { AccountResponse } from "@/domain/entities";
import { ApiError } from "@/domain/errors";
import { classifyGatewayError } from "@/application/gatewayError";
import { accountGateway } from "@/infrastructure/container";

/** How `/api/me` went, in the terms the Account panel draws:
 *  - `unavailable`: 503, the server has no sign-in configured. Calm, not red.
 *  - `rejected`: 401, this server did not accept the session (a token from a
 *    different project, or one revoked since). Offer to sign out.
 *  - `failed`: anything else; retry. */
export type AccountProblem =
  | { kind: "unavailable" }
  | { kind: "rejected" }
  | { kind: "failed"; message: string };

type Loaded = { userId: string; account: AccountResponse | null; problem: AccountProblem | null };

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

  useEffect(() => {
    if (!userId) return;
    let cancelled = false;
    accountGateway
      .fetchAccount()
      .then((account) => {
        if (!cancelled) setLoaded({ userId, account, problem: null });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const status = err instanceof ApiError ? err.status : undefined;
        const problem: AccountProblem =
          status === 503
            ? { kind: "unavailable" }
            : status === 401
              ? { kind: "rejected" }
              : { kind: "failed", message: classifyGatewayError(err, FALLBACK).message };
        setLoaded({ userId, account: null, problem });
      });
    return () => {
      cancelled = true;
    };
  }, [userId, attempt]);

  const reload = useCallback(() => {
    setLoaded(null);
    setAttempt((n) => n + 1);
  }, []);

  const current = userId && loaded?.userId === userId ? loaded : null;
  return {
    account: current?.account ?? null,
    problem: current?.problem ?? null,
    loading: userId !== null && current === null,
    reload,
  };
}
