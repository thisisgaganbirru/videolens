"use client";

import type { MouseEvent } from "react";
import type { FreeRunsBanner as FreeRunsBannerState } from "@/application/useFreeRuns";
import { goToMainTab, mainTabHref } from "@/application/useMainTab";
import { isPlainLeftClick } from "@/components/navClick";
import { formatClockTime, formatDay } from "@/components/format";
import { ACCOUNT_FREE_RUNS_PER_DAY, PAID_EXTRA_RUNS_PER_MONTH } from "@/application/accountAllowance";

/* Hallmark · component: banner · genre: editorial · theme: custom (app/tokens.css)
 * boards: design/shots/IntakeFreeApp.png (runs left), IntakeLimitApp.png (spent)
 * states: hidden · runs left (plural / singular) · spent · link hover · focus-visible · active
 *         × scope device / account (2026-11-13) × period day / month (2026-11-14)
 * contrast: ink on surface 17.6:1 light / 15.4:1 dark; danger-border is a
 *           decorative outline only — the words carry the state, not the red.
 *
 * The free-run allowance, above the intake's eyebrow on every shell (installed
 * app, phone web, desktop web). One white strip of text, no button (UX fix
 * spec, 2026-11-14: the "Add key" pill was the loudest control on Analyze and
 * offered the key ahead of sign-in and the paid plan). The spent state swaps
 * the sentence and gives the strip a red hairline; the way out is offered in
 * the intake card (UploadForm's out-of-runs block), not here. Nothing else turns red — the
 * blocked Analyze button greys out (UploadForm), it does not shout.
 *
 * Reset time (2026-11-14): the local clock time from `resetsAt` through
 * `formatClockTime` (the Account formatter), or the date for a monthly
 * period. Never "tomorrow" or "midnight"; when the time is unknown the
 * sentence is left out.
 *
 * The live region is the always-present wrapper in HomeScreen, not this
 * component: a region that appears with its content announces nothing.
 *
 * Account scope (2026-11-13): a signed-in person is counted on the account
 * instead of the device. Since 2026-11-14 the free account counts a UTC day
 * (10), like the device (3), so the count reads "today" either way and the
 * spent line says when it comes back (the local reset time). The period
 * comes from the server's `period` (inferred by plan when absent).
 *
 * Paid plan (2026-11-13; 30 a day since 2026-11-14): the same strip counts
 * the paid runs ("N of 30 runs left today."). Past the allowance runs go on
 * and are billed, so the spent line states the per-run price and the monthly
 * cap on extra runs instead of turning red.
 *
 * Signed out with runs left (2026-11-14, Android QA): the device line says
 * "today" and, where sign-in is offered, one inline "Sign in for 10 a
 * day" after the reset time, so the device tier and the account tier read as two tiers. The
 * constant lives in application/accountAllowance.ts. */

function openAccount(event: MouseEvent<HTMLAnchorElement>) {
  if (!isPlainLeftClick(event)) return;
  event.preventDefault();
  goToMainTab("account");
}

export default function FreeRunsBanner({
  banner,
  offerSignIn = false,
  extraRunPrice = null,
}: {
  banner: FreeRunsBannerState;
  /** Sign-in works here and nobody is signed in: the runs-left line points
   *  at the account allowance, once, quietly. */
  offerSignIn?: boolean;
  /** Kept for callers; since 2026-11-14 the upgrade offer lives in the intake
   *  card (UploadForm `blockedOffer`), so the strip no longer reads it. */
  offerUpgrade?: boolean;
  /** The price of one run past the paid allowance, formatted ("$0.15");
   *  null when billing has not said. */
  extraRunPrice?: string | null;
}) {
  const { remaining, exhausted, scope, limit, plan, overage, period, resetsAt } = banner;
  const account = scope === "account";
  const monthly = period === "month";
  const periodWord = monthly ? "this month" : "today";
  const periodPossessive = monthly ? "this month's" : "today's";
  const unit = limit === 1 ? "run" : "runs";
  const resetText = monthly
    ? resetsAt && !Number.isNaN(Date.parse(resetsAt))
      ? formatDay(resetsAt)
      : null
    : formatClockTime(resetsAt);
  const resetLeft = resetText ? ` ${monthly ? "Resets on" : "Resets at"} ${resetText}.` : "";
  const resetSpent = resetText ? ` ${monthly ? "They reset on" : "They reset at"} ${resetText}.` : "";
  const leftLine = (
    <strong>
      {remaining} of {limit} {unit} left {periodWord}.
    </strong>
  );
  const spentLine = (
    <strong>
      {limit > 0 ? `You've used ${periodPossessive} ${limit} ${unit}.` : `You've used ${periodPossessive} runs.`}
    </strong>
  );

  if (plan === "paid") {
    /* Spent without overage would block; it is not expected (the server
       bills extra runs), but say the true thing if it happens. */
    const stopped = exhausted && !overage;
    return (
      <div className="free-runs" data-state={stopped ? "spent" : "left"} data-scope={scope} data-plan="paid">
        <p className="free-runs__text">
          {!exhausted ? (
            <>
              {leftLine}
              {resetLeft}
            </>
          ) : overage ? (
            <>
              {spentLine}{" "}
              {extraRunPrice
                ? `Extra runs are billed at ${extraRunPrice} each, up to ${PAID_EXTRA_RUNS_PER_MONTH} a month.`
                : `Extra runs are billed per run, up to ${PAID_EXTRA_RUNS_PER_MONTH} a month.`}
            </>
          ) : (
            <>
              {spentLine}
              {resetSpent}
            </>
          )}
        </p>
      </div>
    );
  }

  return (
    <div className="free-runs" data-state={exhausted ? "spent" : "left"} data-scope={scope}>
      <p className="free-runs__text">
        {exhausted ? (
          <>
            {spentLine}
            {resetSpent}
          </>
        ) : (
          <>
            {leftLine}
            {resetLeft}
            {!account && offerSignIn ? (
              <>
                {" "}
                <a className="text-link" href={mainTabHref("account")} onClick={openAccount}>
                  Sign in
                </a>{" "}
                for {ACCOUNT_FREE_RUNS_PER_DAY} a day.
              </>
            ) : null}
          </>
        )}
      </p>
    </div>
  );
}
