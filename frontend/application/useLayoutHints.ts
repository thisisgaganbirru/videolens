"use client";

import { useEffect } from "react";
import type { BillingPlan } from "@/domain/entities";
import { forgetRunsSpent, rememberPlan, rememberRunsSpent, type SpentOffer } from "@/infrastructure/layoutHints";

/* Keeps the pre-paint layout hints (infrastructure/layoutHints.ts) in step
   with what the reads say, so the next visit reserves the right stand-ins
   from the first paint. Called once, from the always-mounted shell. */

/**
 * The allowance as the intake shows it. `known`: the strip and the block are
 * final for this identity (sign-in state and the allowance have answered).
 * `blocked`: analyzing is paused. `available`: a read says runs can be
 * started (runs left, billed overage, or the user's own key).
 */
export function useRememberRunsSpent({
  known,
  blocked,
  available,
  resetsAt,
  offer,
}: {
  known: boolean;
  blocked: boolean;
  available: boolean;
  resetsAt: string;
  offer: SpentOffer;
}): void {
  useEffect(() => {
    if (!known) return;
    if (blocked) rememberRunsSpent(resetsAt, offer);
    else if (available) forgetRunsSpent();
    /* Otherwise (a failed read, a deployment without a limit) the hint is
       left to expire at its own reset time. */
  }, [known, blocked, available, resetsAt, offer]);
}

/**
 * `plan`: the signed-in account's plan once a read has named it, else null.
 * `signedOut`: the session is known and nobody is signed in.
 * `complimentary`: that read said complimentary Plus (2026-11-14), which has
 * no Billing card, so its stand-in is no card at all.
 */
export function useRememberPlan(plan: BillingPlan | null, signedOut: boolean, complimentary = false): void {
  useEffect(() => {
    if (signedOut) rememberPlan(false);
    else if (plan) rememberPlan(plan === "paid", plan === "paid" && complimentary);
  }, [plan, signedOut, complimentary]);
}
