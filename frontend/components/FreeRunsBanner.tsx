"use client";

import type { MouseEvent } from "react";
import type { FreeRunsBanner as FreeRunsBannerState } from "@/application/useFreeRuns";
import { goToMainTab, mainTabHref } from "@/application/useMainTab";
import { isPlainLeftClick } from "@/components/navClick";
import {
  ACCOUNT_FREE_RUNS_PER_DAY,
  PAID_EXTRA_RUNS_PER_MONTH,
  PAID_RUNS_PER_DAY,
} from "@/application/accountAllowance";

/* Hallmark · component: banner · genre: editorial · theme: custom (app/tokens.css)
 * boards: design/shots/IntakeFreeApp.png (runs left), IntakeLimitApp.png (spent)
 * states: hidden · runs left (plural / singular) · spent · link hover · focus-visible · active
 *         × scope device / account (2026-11-13) × period day / month (2026-11-14)
 * contrast: ink on surface 17.6:1 light / 15.4:1 dark; danger-border is a
 *           decorative outline only — the words carry the state, not the red.
 *
 * The free-run allowance, above the intake's eyebrow on every shell (installed
 * app, phone web, desktop web). One white strip, the sentence on the left and
 * the near-black "Add key" pill on the right; the spent state swaps the
 * sentence and gives the strip a red hairline. Nothing else turns red — the
 * blocked Analyze button greys out (UploadForm), it does not shout.
 *
 * "Add key" is a link, not a button: it goes somewhere (the API key view,
 * `/app?view=api-key`), so it keeps a real href for middle-click and new-tab, and
 * switches tabs in place on a plain click like every other tab link.
 *
 * The live region is the always-present wrapper in HomeScreen, not this
 * component: a region that appears with its content announces nothing.
 *
 * Account scope (2026-11-13): a signed-in person is counted on the account
 * instead of the device. Since 2026-11-14 the free account counts a UTC day
 * (10), like the device (3), so the count reads "today" either way and the
 * spent account line says when it comes back ("They reset tomorrow."). The
 * period comes from the server's `period` (inferred by plan when absent). Signed out and spent, where sign-in is offered, one quiet
 * inline link says what signing in would give; no new chrome.
 *
 * Paid plan (2026-11-13; 30 a day since 2026-11-14): the same strip counts
 * the paid runs ("N of 30 runs left today."), with no "Add key" pill, since
 * the plan needs no key. Past the allowance runs go on and are billed, so
 * the spent line states the per-run price and the monthly cap on extra runs
 * instead of turning red. A free account that has spent its day gets one
 * quiet "upgrade" link to the Account tab, naming the paid daily count, only
 * where the server sells the plan.
 *
 * Signed out with runs left (2026-11-14, Android QA): the device line says
 * "today" and, where sign-in is offered, one inline "Sign in for 10 a
 * day", so the device tier and the account tier read as two tiers. The
 * constant lives in application/accountAllowance.ts. */

function openApiKey(event: MouseEvent<HTMLAnchorElement>) {
  if (!isPlainLeftClick(event)) return;
  event.preventDefault();
  goToMainTab("api-key");
}

function openAccount(event: MouseEvent<HTMLAnchorElement>) {
  if (!isPlainLeftClick(event)) return;
  event.preventDefault();
  goToMainTab("account");
}

export default function FreeRunsBanner({
  banner,
  offerSignIn = false,
  offerUpgrade = false,
  extraRunPrice = null,
}: {
  banner: FreeRunsBannerState;
  /** Sign-in works here and nobody is signed in: the device line (runs
   *  left or spent) points at the account allowance, once, quietly. */
  offerSignIn?: boolean;
  /** The server sells the paid plan and this account is on the free one:
   *  the spent account line may point at it. */
  offerUpgrade?: boolean;
  /** The price of one run past the paid allowance, formatted ("$0.15");
   *  null when billing has not said. */
  extraRunPrice?: string | null;
}) {
  const { remaining, exhausted, scope, limit, plan, overage, period } = banner;
  const account = scope === "account";
  const monthly = period === "month";

  if (plan === "paid") {
    /* Spent without overage would block; it is not expected (the server
       bills extra runs), but say the true thing if it happens. */
    const stopped = exhausted && !overage;
    return (
      <div className="free-runs" data-state={stopped ? "spent" : "left"} data-scope={scope} data-plan="paid">
        <p className="free-runs__text">
          {!exhausted ? (
            <strong>
              {remaining} of {limit} {limit === 1 ? "run" : "runs"} left {monthly ? "this month" : "today"}.
            </strong>
          ) : overage ? (
            <>
              <strong>You have used {monthly ? "this month" : "today"}&apos;s {limit} runs.</strong>{" "}
              {extraRunPrice
                ? `Extra runs are billed at ${extraRunPrice} each, up to ${PAID_EXTRA_RUNS_PER_MONTH} a month.`
                : `Extra runs are billed per run, up to ${PAID_EXTRA_RUNS_PER_MONTH} a month.`}
            </>
          ) : (
            <>
              <strong>You have used {monthly ? "this month" : "today"}&apos;s {limit} runs.</strong> Add your own Gemini key to keep going.
            </>
          )}
        </p>
        {stopped && (
          <a className="btn btn-ink btn-pill free-runs__action" href={mainTabHref("api-key")} onClick={openApiKey}>
            Add key
          </a>
        )}
      </div>
    );
  }

  return (
    <div className="free-runs" data-state={exhausted ? "spent" : "left"} data-scope={scope}>
      <p className="free-runs__text">
        {exhausted ? (
          account ? (
            <>
              <strong>
                {monthly
                  ? "You have used this month's free runs."
                  : limit > 0
                    ? `You have used today's ${limit} free runs.`
                    : "You have used today's free runs."}
              </strong>{" "}
              {monthly ? "" : "They reset tomorrow. "}
              {offerUpgrade ? (
                <>
                  Add your own Gemini key to keep going, or{" "}
                  <a className="text-link" href={mainTabHref("account")} onClick={openAccount}>
                    upgrade
                  </a>{" "}
                  for {PAID_RUNS_PER_DAY} a day.
                </>
              ) : (
                "Add your own Gemini key to keep going."
              )}
            </>
          ) : offerSignIn ? (
            <>
              <strong>You have used your free runs.</strong> Add your own key, or{" "}
              <a className="text-link" href={mainTabHref("account")} onClick={openAccount}>
                sign in
              </a>{" "}
              for {ACCOUNT_FREE_RUNS_PER_DAY} free runs a day.
            </>
          ) : (
            <>
              <strong>You have used your free runs.</strong> Add your own key to keep going.
            </>
          )
        ) : (
          <>
            <strong>
              {remaining} free {remaining === 1 ? "run" : "runs"} left {monthly ? "this month" : "today"}.
            </strong>{" "}
            {!account && offerSignIn ? (
              <>
                <a className="text-link" href={mainTabHref("account")} onClick={openAccount}>
                  Sign in
                </a>{" "}
                for {ACCOUNT_FREE_RUNS_PER_DAY} a day, or add your own key.
              </>
            ) : (
              "Add your own key for more."
            )}
          </>
        )}
      </p>
      <a className="btn btn-ink btn-pill free-runs__action" href={mainTabHref("api-key")} onClick={openApiKey}>
        Add key
      </a>
    </div>
  );
}
