/** A calendar day with its year ("Aug 31, 2026") — for things that are dated,
 *  not timed, like a release. (History formats its own dates; see history.ts.) */
export function formatDay(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

/** A full calendar date ("December 13, 2026"), for a plan's renewal or end. */
export function formatLongDay(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    month: "long",
    day: "numeric",
    year: "numeric",
  });
}

/** A price given in the currency's minor units (Stripe's `amount`), as the
 *  app says it: "$12" for a whole amount, "$0.15" otherwise. The minor-unit
 *  exponent comes from Intl (2 for usd, 0 for jpy), not a hard-coded 100.
 *  Null for a currency Intl does not know. */
export function formatPrice(price: { amount: number; currency: string }): string | null {
  try {
    const currency = price.currency.toUpperCase();
    const digits = new Intl.NumberFormat("en-US", { style: "currency", currency }).resolvedOptions()
      .maximumFractionDigits ?? 2;
    const value = price.amount / 10 ** digits;
    const whole = price.amount % 10 ** digits === 0;
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      currencyDisplay: "narrowSymbol",
      minimumFractionDigits: whole ? 0 : digits,
      maximumFractionDigits: digits,
    }).format(value);
  } catch {
    return null;
  }
}
