import type { MediaLimits, MediaLimitsTable } from "@/domain/entities";
import { ApiError, NetworkError } from "@/domain/errors";
import type { LimitsGateway } from "@/domain/ports";
import { API_BASE_URL } from "./apiBase";

/* `GET /api/limits` (2026-11-13): how long and how large an upload may be,
   per tier. Contract:

     {"standard":       {"max_duration_seconds": 180, "max_file_size_mb": 200},
      "signed_in_byok": {"max_duration_seconds": 600, "max_file_size_mb": 500},
      "paid":           {"max_duration_seconds": 600, "max_file_size_mb": 500}}

   Public and about the server, like `/api/capabilities`, so it carries no
   caller identity: no client id, no bearer, never the Gemini key.

   Normalises rather than casts. A server from before this endpoint answers
   404, and a malformed body must not hand the intake an `undefined` limit;
   both reject here, and `useMediaLimits` falls back to the standard values. A
   tier that is missing or unreadable on its own falls back the same way
   (signed_in_byok to the body's own standard), so a half-readable answer can
   never advertise more than the server is known to allow. */

const UNREACHABLE = "Can't reach the server. It may be offline, or your connection dropped.";
const UNREADABLE = "The server replied with something this app could not read.";

function positive(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : null;
}

function tier(raw: unknown): MediaLimits | null {
  if (typeof raw !== "object" || raw === null) return null;
  const row = raw as Record<string, unknown>;
  const maxDurationSeconds = positive(row.max_duration_seconds);
  const maxFileSizeMb = positive(row.max_file_size_mb);
  if (maxDurationSeconds === null || maxFileSizeMb === null) return null;
  return { maxDurationSeconds, maxFileSizeMb };
}

function normalise(raw: unknown): MediaLimitsTable {
  const body = (typeof raw === "object" && raw !== null ? raw : {}) as Record<string, unknown>;
  const standard = tier(body.standard);
  if (!standard) throw new ApiError(UNREADABLE);
  /* `paid` (2026-11-13) is optional: missing or unreadable is null, and the
     paid plan then gets the same limits as everyone else. */
  return { standard, signedInByok: tier(body.signed_in_byok) ?? standard, paid: tier(body.paid) };
}

export class FetchLimitsGateway implements LimitsGateway {
  async fetchLimits(): Promise<MediaLimitsTable> {
    let res: Response;
    try {
      res = await fetch(`${API_BASE_URL}/api/limits`);
    } catch {
      throw new NetworkError(UNREACHABLE);
    }
    if (!res.ok) throw new ApiError(`Could not read limits (${res.status})`, res.status);
    let raw: unknown;
    try {
      raw = await res.json();
    } catch {
      throw new ApiError(UNREADABLE);
    }
    return normalise(raw);
  }
}
