/* The backend's origin, in one place.
 *
 * It lived as a module-local const inside `runsGateway.ts` while that was the
 * only adapter talking to the API. `capabilitiesGateway.ts` is the second, and
 * two copies of an environment-variable fallback is exactly the kind of thing
 * that drifts silently: the copy nobody edits keeps pointing at localhost in a
 * deployment where the other one was fixed, and the symptom is one feature
 * quietly failing rather than a build error. */
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
