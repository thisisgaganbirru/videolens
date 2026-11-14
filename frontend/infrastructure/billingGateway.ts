import type { BillingInterval, BillingPrice, BillingStatus } from "@/domain/entities";
import { ApiError } from "@/domain/errors";
import type { BillingGateway } from "@/domain/ports";
import type { ApiClient } from "./apiClient";
import { UNREADABLE } from "./apiClient";

/* `/api/billing*` (2026-11-13, one paid plan; contract in
   docs/frontend/billing.md). Sent through `ApiClient`, so the bearer rides
   along; anonymous callers get 401 and the hook never asks for them.

   Checkout and the portal are Stripe-hosted pages reached by a top-level
   redirect. This adapter only asks the server where to go: no Stripe.js, no
   card data, nothing from Stripe in this origin. The URL that comes back is
   checked to be https before anyone navigates to it.

   Normalises like the free-runs adapter: the Plan group is optional chrome,
   so a malformed body must become an error the hook goes quiet on, never a
   render crash on the Account tab. Any price may be null and hides its
   button. */

function count(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? Math.floor(value) : null;
}

function price(raw: unknown): BillingPrice | null {
  if (typeof raw !== "object" || raw === null) return null;
  const row = raw as Record<string, unknown>;
  const amount = count(row.amount);
  if (amount === null || typeof row.currency !== "string" || !/^[a-z]{3}$/i.test(row.currency)) return null;
  return { amount, currency: row.currency.toLowerCase() };
}

function normalise(raw: unknown): BillingStatus {
  const body = (typeof raw === "object" && raw !== null ? raw : {}) as Record<string, unknown>;
  /* Only a literal `true` turns billing on: the failure to avoid is drawing
     a Plan group on a server that cannot sell one. */
  if (body.enabled !== true) return { enabled: false };
  const runs = (typeof body.runs === "object" && body.runs !== null ? body.runs : {}) as Record<string, unknown>;
  const limit = count(runs.limit);
  const used = count(runs.used);
  if (limit === null || used === null) throw new ApiError(UNREADABLE);
  const prices = (typeof body.prices === "object" && body.prices !== null ? body.prices : {}) as Record<
    string,
    unknown
  >;
  return {
    enabled: true,
    plan: body.plan === "paid" ? "paid" : "free",
    status: typeof body.status === "string" && body.status ? body.status : null,
    interval: body.interval === "month" || body.interval === "year" ? body.interval : null,
    currentPeriodEnd:
      typeof body.current_period_end === "string" && !Number.isNaN(Date.parse(body.current_period_end))
        ? body.current_period_end
        : null,
    cancelAtPeriodEnd: body.cancel_at_period_end === true,
    runs: { limit, used },
    prices: { month: price(prices.month), year: price(prices.year), extraRun: price(prices.extra_run) },
  };
}

/** The redirect target, only if it is a plain https address. */
function redirectUrl(raw: unknown): string {
  const value = typeof raw === "object" && raw !== null ? (raw as Record<string, unknown>).url : null;
  if (typeof value === "string") {
    try {
      const url = new URL(value);
      if (url.protocol === "https:") return url.href;
    } catch {
      /* fall through */
    }
  }
  throw new ApiError(UNREADABLE);
}

export class FetchBillingGateway implements BillingGateway {
  constructor(private readonly client: ApiClient) {}

  async fetchBilling(): Promise<BillingStatus> {
    const raw = await this.client.json<unknown>("/api/billing", {}, "Could not load your plan");
    return normalise(raw);
  }

  async startCheckout(interval: BillingInterval): Promise<string> {
    const raw = await this.client.jsonBody<unknown>(
      "/api/billing/checkout",
      "POST",
      { interval },
      "Could not start checkout"
    );
    return redirectUrl(raw);
  }

  async openPortal(): Promise<string> {
    const raw = await this.client.jsonBody<unknown>("/api/billing/portal", "POST", {}, "Could not open billing");
    return redirectUrl(raw);
  }
}
