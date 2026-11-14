"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { useFreeRuns } from "@/application/useFreeRuns";
import { durationLabel, useMediaLimits } from "@/application/useMediaLimits";
import { useAuthUser } from "@/application/useAuthSession";
import { useAccountEntry } from "@/application/useAccountEntry";
import { mainTabHref } from "@/application/useMainTab";
import { ACCOUNT_FREE_RUNS_PER_DAY } from "@/application/accountAllowance";

/* Hallmark · component: hero note · genre: editorial · theme: custom (app/tokens.css)
 * states: fallback (prerender / server unreachable) · device · account · paid · own key
 *
 * The two quiet lines under the landing hero's actions (2026-11-14). The
 * page is prerendered, so the HTML carries the fallback sentence, which is
 * true on any deployment; the numbers replace it once the server has said
 * them, from the same reads `/app` makes (free runs, upload limits, the auth
 * gate). Nothing is hard-coded except the account allowance, which signed-out
 * copy quotes everywhere from `ACCOUNT_FREE_RUNS_PER_DAY`. The period ("a
 * day" / "a month") is the server's `period`, inferred by plan when absent.
 *
 * Line one is the free-run tier this visitor is on; line two the video length
 * and, signed out where sign-in exists, the other tier, so "3 a day" and
 * "Sign in for 10 a day" read as two tiers rather than two different claims
 * (both daily since 2026-11-14, so signing in reads as more, not different). That inline
 * "Sign in" is also the phone's visible account entry (the bar pill is hidden
 * below 48rem). Line two reserves its height in CSS, so the hero does not move
 * when it fills in.
 *
 * Same type vocabulary as the Analyze free-runs strip: ink-2 sentence, the
 * count in a 600-weight ink `strong`; the second line muted. */
export default function LandingAllowance() {
  const auth = useAuthUser();
  const entry = useAccountEntry();
  const freeRuns = useFreeRuns(auth.ready ? (auth.user?.id ?? "") : null);
  const media = useMediaLimits(Boolean(auth.user));
  const banner = freeRuns.banner;

  const per = banner?.period === "month" ? "a month" : "a day";

  let tier: ReactNode = "Free runs to start. No account needed.";
  if (media.hasKey) {
    tier = "Runs use the Gemini key saved in this browser.";
  } else if (banner?.plan === "paid") {
    tier = (
      <>
        <strong>
          {banner.limit} {banner.limit === 1 ? "run" : "runs"} {per}
        </strong>{" "}
        on your plan.
      </>
    );
  } else if (banner?.scope === "account") {
    tier = (
      <>
        <strong>
          {banner.limit} free {banner.limit === 1 ? "run" : "runs"} {per}
        </strong>{" "}
        with your account.
      </>
    );
  } else if (banner) {
    tier = (
      <>
        <strong>
          {banner.limit} free {banner.limit === 1 ? "run" : "runs"} {per}
        </strong>
        , no account needed.
      </>
    );
  }

  const offerSignIn = entry.showAccount && entry.accountState === "signed-out";

  return (
    <div className="landing-allowance">
      <p className="landing-allowance__tier">{tier}</p>
      <p className="landing-allowance__more">
        {media.known && <>Videos up to {durationLabel(media.limits.maxDurationSeconds)}.</>}
        {media.known && offerSignIn && " "}
        {offerSignIn && (
          <>
            <Link href={mainTabHref("account")} className="text-link">
              Sign in
            </Link>{" "}
            for {ACCOUNT_FREE_RUNS_PER_DAY} a day.
          </>
        )}
      </p>
    </div>
  );
}
