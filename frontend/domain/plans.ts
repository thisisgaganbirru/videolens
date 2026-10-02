/* The plan table as the account panel presents it. The numbers that gate
   anything live on the backend (`app/domain/entitlements.py`) and arrive
   through `GET /api/me`; this is only what a card says before you buy. Keep
   the two in step — a price shown here that Stripe does not charge is a
   support ticket, not a bug report. */

import type { Plan } from "./entities";

export type PlanCard = {
  plan: Plan;
  name: string;
  /** Monthly price in USD, or 0 for free. */
  priceUsd: number;
  minutesIncluded: number;
  maxDurationMinutes: number;
  seats: number;
  overageUsdPerMinute: number | null;
  perks: string[];
};

export const PLAN_CARDS: readonly PlanCard[] = [
  {
    plan: "free",
    name: "Free",
    priceUsd: 0,
    minutesIncluded: 30,
    maxDurationMinutes: 3,
    seats: 1,
    overageUsdPerMinute: null,
    perks: ["30 minutes of media a month", "Bring your own Gemini key for unlimited runs", "Recent history only"],
  },
  {
    plan: "pro",
    name: "Pro",
    priceUsd: 19,
    minutesIncluded: 600,
    maxDurationMinutes: 30,
    seats: 1,
    overageUsdPerMinute: 0.05,
    perks: ["600 minutes a month", "Videos up to 30 minutes", "Searchable library of every run"],
  },
  {
    plan: "studio",
    name: "Studio",
    priceUsd: 79,
    minutesIncluded: 3000,
    maxDurationMinutes: 60,
    seats: 3,
    overageUsdPerMinute: 0.05,
    perks: ["3,000 minutes a month", "Videos up to 60 minutes", "3 seats", "API keys and the MCP server"],
  },
  {
    plan: "scale",
    name: "Scale",
    priceUsd: 299,
    minutesIncluded: 12000,
    maxDurationMinutes: 120,
    seats: 10,
    overageUsdPerMinute: 0.04,
    perks: ["12,000 minutes a month", "Videos up to 2 hours", "10 seats", "API keys, MCP server, priority queue"],
  },
];

const ORDER: Record<Plan, number> = { free: 0, pro: 1, studio: 2, scale: 3 };

export function isPlan(value: string): value is Plan {
  return value in ORDER;
}

/** Whether `candidate` is a step up from `current`. Unknown plans compare as
 *  free, so an unrecognised current plan still shows every upgrade. */
export function isUpgrade(current: string, candidate: Plan): boolean {
  const from = isPlan(current) ? ORDER[current] : 0;
  return ORDER[candidate] > from;
}
