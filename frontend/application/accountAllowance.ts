/* The signed-in monthly free-run allowance, as the owner set it (2026-11-13).
   Only quoted to signed-out people, who have no account read to take it from;
   signed-in copy always uses the server's own `limit`. Quoted by the Analyze
   free-runs strip, the Account panel's signed-out lede, and the landing page
   (its nav label and allowance line).

   A plain module, not "use client", on purpose: the landing page is a server
   component, and a constant exported from a client module reaches a server
   component as a client reference, not as the number. */
export const ACCOUNT_FREE_RUNS_PER_MONTH = 10;
