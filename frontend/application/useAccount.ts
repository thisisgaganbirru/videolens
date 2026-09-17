"use client";

import { useCallback, useEffect, useState } from "react";
import type { AccountResponse, Plan } from "@/domain/entities";
import { classifyGatewayError, type GatewayError } from "@/application/gatewayError";
import { accountGateway } from "@/infrastructure/container";

const UNKNOWN_FALLBACK = "Your account could not be loaded.";

/**
 * `GET /api/me` for whoever is calling, plus the two money-shaped actions.
 *
 * `userId` is the dependency that refetches: when someone signs in or out the
 * answer changes, and the caller (the account panel) passes the current
 * user's id so the effect re-runs on that transition. The checkout and portal
 * calls resolve with a URL the browser is sent to; on the way back Stripe
 * lands on `/?view=account&checkout=success`, which the panel reads to know
 * a refetch is worth doing.
 */
export function useAccount(userId: string | null) {
  const [account, setAccount] = useState<AccountResponse | null>(null);
  const [error, setError] = useState<GatewayError | null>(null);
  const [busy, setBusy] = useState<"checkout" | "portal" | null>(null);
  const [actionError, setActionError] = useState<GatewayError | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    accountGateway
      .fetchAccount()
      .then((next) => {
        if (cancelled) return;
        setAccount(next);
        setError(null);
      })
      .catch((err) => {
        if (!cancelled) setError(classifyGatewayError(err, UNKNOWN_FALLBACK));
      });
    return () => {
      cancelled = true;
    };
  }, [userId, attempt]);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);

  const upgrade = useCallback(
    async (plan: Plan) => {
      if (busy) return;
      setBusy("checkout");
      setActionError(null);
      try {
        const url = await accountGateway.startCheckout(plan);
        window.location.assign(url);
      } catch (err) {
        setActionError(classifyGatewayError(err, "Checkout could not be started."));
        setBusy(null);
      }
    },
    [busy],
  );

  const manageBilling = useCallback(async () => {
    if (busy) return;
    setBusy("portal");
    setActionError(null);
    try {
      const url = await accountGateway.openBillingPortal();
      window.location.assign(url);
    } catch (err) {
      setActionError(classifyGatewayError(err, "Billing could not be opened."));
      setBusy(null);
    }
  }, [busy]);

  return { account, error, reload, upgrade, manageBilling, busy, actionError };
}
