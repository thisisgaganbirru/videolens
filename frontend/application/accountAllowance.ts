/* The signed-in free-run allowance, as the owner set it: 10 per UTC day
   (2026-11-14; it was 10 a month from 2026-11-13, which made signing in look
   like a downgrade from the anonymous 3 a day). Only quoted to signed-out
   people, who have no account read to take it from; signed-in copy always
   uses the server's own `limit` and `period`. Quoted by the Analyze
   free-runs strip, the Account panel's signed-out lede, and the landing page
   (its nav label and allowance line).

   A plain module, not "use client", on purpose: the landing page is a server
   component, and a constant exported from a client module reaches a server
   component as a client reference, not as the number. */
export const ACCOUNT_FREE_RUNS_PER_DAY = 10;

/* The paid plan's allowance, as the owner set it on 2026-11-14: 30 runs per
   UTC day on our Gemini key (it was 100 a month from 2026-11-13, less than a
   free account's 10 a day over a month). Runs past the 30 are billed per
   run, with a hard cap on those extra runs per calendar month. Quoted only
   where no paid read exists yet (the free plan's pitch, whose `runs.limit`
   is the free allowance); a paid account's copy uses the server's own
   `limit` and `period`. The extra-run cap is not in any response body until
   a 402 `extra_runs_cap` names it, so the pitch quotes it from here. */
export const PAID_RUNS_PER_DAY = 30;
export const PAID_EXTRA_RUNS_PER_MONTH = 200;
