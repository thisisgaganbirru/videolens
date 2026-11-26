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

/** An instant as a clock time in the reader's own time zone ("7:00 PM",
 *  "19:00" where the locale uses 24 hours), for when a daily count resets.
 *  The server's instant is UTC midnight, which is not the reader's midnight.
 *  Null for an empty or unreadable instant. */
export function formatClockTime(iso: string): string | null {
  if (!iso) return null;
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return null;
  return at.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}
