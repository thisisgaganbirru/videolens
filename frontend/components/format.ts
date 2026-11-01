/** A calendar day with its year ("Aug 31, 2026") — for things that are dated,
 *  not timed, like a release. (History formats its own dates; see history.ts.) */
export function formatDay(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}
