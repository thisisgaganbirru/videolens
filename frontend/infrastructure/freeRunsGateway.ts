import type { FreeRunsStatus } from "@/domain/entities";
import { ApiError, NetworkError } from "@/domain/errors";
import type { DeviceTokenStore, FreeRunsGateway } from "@/domain/ports";
import { API_BASE_URL } from "./apiBase";
import { getClientId } from "./clientId";

/* `GET /api/free-runs` (Phase 5b; contract in docs/frontend/free-runs.md).

   Sends the stored `X-Device-Token` (when there is one) and the usual
   `X-Client-ID`, never the Gemini key — this endpoint does not read it. The
   server answers with the token it counts against: the same one, or a fresh
   one when ours was missing or invalid. Whatever it says is written back to
   the store here, so the next `POST /api/runs` carries the token the count
   belongs to.

   Like the capabilities adapter, this normalises rather than casting: the
   banner it feeds is optional chrome, so a malformed body must become an
   error the hook goes quiet on, never a render crash on the intake. */

const UNREACHABLE = "Can't reach the server. It may be offline, or your connection dropped.";
const UNREADABLE = "The server replied with something this app could not read.";

function count(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? Math.floor(value) : null;
}

function normalise(raw: unknown): FreeRunsStatus {
  const body = (typeof raw === "object" && raw !== null ? raw : {}) as Record<string, unknown>;
  const limit = count(body.limit);
  const used = count(body.used);
  const remaining = count(body.remaining);
  if (typeof body.device_token !== "string" || limit === null || used === null || remaining === null) {
    throw new ApiError(UNREADABLE);
  }
  return {
    deviceToken: body.device_token,
    limit,
    used,
    remaining,
    resetsAt: typeof body.resets_at === "string" ? body.resets_at : "",
    /* Anything but a literal `false` keeps the limit on: the failure to avoid
       is hiding a limit that will then refuse the user's next run. */
    enabled: body.enabled !== false,
  };
}

export class FetchFreeRunsGateway implements FreeRunsGateway {
  constructor(private readonly deviceTokenStore: DeviceTokenStore) {}

  async fetchStatus(): Promise<FreeRunsStatus> {
    const headers: Record<string, string> = { "X-Client-ID": getClientId() };
    const token = this.deviceTokenStore.get();
    if (token) headers["X-Device-Token"] = token;

    let res: Response;
    try {
      res = await fetch(`${API_BASE_URL}/api/free-runs`, { headers });
    } catch {
      throw new NetworkError(UNREACHABLE);
    }
    if (!res.ok) throw new ApiError(`Could not read free runs (${res.status})`, res.status);

    let raw: unknown;
    try {
      raw = await res.json();
    } catch {
      throw new ApiError(UNREADABLE);
    }
    const status = normalise(raw);
    if (status.deviceToken && status.deviceToken !== token) {
      this.deviceTokenStore.set(status.deviceToken);
    }
    return status;
  }
}
