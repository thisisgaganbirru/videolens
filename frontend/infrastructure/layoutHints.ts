/* Pre-paint layout hints (2026-11-14), the same pattern as `data-byok`
   (apiKeyStore.ts) and `data-session` (authSessionStamp.ts). The prerendered
   pages cannot know what the first reads will say, so the last answer is
   remembered here and stamped on <html> before the first paint; CSS then
   reserves the right stand-in. These are layout hints only, never state the
   app acts on: every one may be stale, and the real read replaces it.

   - `data-runs-spent="<offer>"`: the last allowance read on this device said
     the runs were spent (and analyzing was paused). Stored with the reset
     instant, so it expires by itself when the runs come back; the pre-paint
     script drops an expired one. `<offer>` is which way out the intake card
     offered (`sign-in`, `upgrade` or `key`), because the block's height
     depends on it. Cleared as soon as a read says runs are available.
   - `data-plan-paid`: the last plan read for the signed-in account was the
     paid plan. Cleared by a free-plan read and on sign-out.

   Every storage access is wrapped: blocked storage means no hint, which is
   the first-visit layout. */

import { SESSION_ATTRIBUTE } from "@/infrastructure/authSessionStamp";

export const RUNS_SPENT_ATTRIBUTE = "data-runs-spent";
export const PLAN_PAID_ATTRIBUTE = "data-plan-paid";

const RUNS_SPENT_KEY = "videolens-runs-spent";
const PLAN_PAID_KEY = "videolens-plan-paid";

export type SpentOffer = "sign-in" | "upgrade" | "key";

function root(): HTMLElement | null {
  return typeof document === "undefined" ? null : document.documentElement;
}

/** The next UTC midnight, for a spent state whose reset time is unknown. */
function nextUtcMidnight(now: number): number {
  const d = new Date(now);
  return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() + 1);
}

/** Remember "spent until `resetsAt`" (ISO; "" or invalid = next UTC midnight). */
export function rememberRunsSpent(resetsAt: string, offer: SpentOffer): void {
  const now = Date.now();
  const parsed = Date.parse(resetsAt);
  const until = Number.isNaN(parsed) || parsed <= now ? nextUtcMidnight(now) : parsed;
  try {
    window.localStorage.setItem(RUNS_SPENT_KEY, `${until} ${offer}`);
  } catch {
    /* storage unavailable: no hint next time */
  }
  root()?.setAttribute(RUNS_SPENT_ATTRIBUTE, offer);
}

export function forgetRunsSpent(): void {
  try {
    window.localStorage.removeItem(RUNS_SPENT_KEY);
  } catch {
    /* nothing to clear */
  }
  root()?.removeAttribute(RUNS_SPENT_ATTRIBUTE);
}

export function rememberPlan(paid: boolean): void {
  try {
    if (paid) window.localStorage.setItem(PLAN_PAID_KEY, "1");
    else window.localStorage.removeItem(PLAN_PAID_KEY);
  } catch {
    /* storage unavailable */
  }
  if (paid) root()?.setAttribute(PLAN_PAID_ATTRIBUTE, "");
  else root()?.removeAttribute(PLAN_PAID_ATTRIBUTE);
}

/* Reads presence and the expiry only. An expired or malformed spent hint is
   removed here, so it never stamps. So is one the session has outgrown: the
   sign-in offer is only for someone signed out and the upgrade offer only
   for someone signed in, so a `sign-in` hint with a stored session (or an
   `upgrade` one without) was written by the other identity. Runs after the
   session stamp, which it reads. */
export const LAYOUT_HINTS_INIT_SCRIPT = `(function(){var r=document.documentElement;try{var v=localStorage.getItem(${JSON.stringify(
  RUNS_SPENT_KEY
)});if(v){var p=v.split(" "),o=p[1];var se=r.hasAttribute(${JSON.stringify(SESSION_ATTRIBUTE)});if(+p[0]>Date.now()&&(o==="key"||(o==="sign-in"&&!se)||(o==="upgrade"&&se)))r.setAttribute(${JSON.stringify(
  RUNS_SPENT_ATTRIBUTE
)},o);else localStorage.removeItem(${JSON.stringify(RUNS_SPENT_KEY)});}if(localStorage.getItem(${JSON.stringify(
  PLAN_PAID_KEY
)}))r.setAttribute(${JSON.stringify(PLAN_PAID_ATTRIBUTE)},"");}catch(e){}})();`;
