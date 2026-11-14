import type { FreeRunsStatus } from "@/domain/entities";
import { ApiError } from "@/domain/errors";
import type { DeviceTokenStore, FreeRunsGateway } from "@/domain/ports";
import type { ApiClient } from "./apiClient";
import { UNREADABLE } from "./apiClient";

/* `GET /api/free-runs` (Phase 5b; contract in docs/frontend/free-runs.md).

   Sends the stored `X-Device-Token` (when there is one), the usual
   `X-Client-ID` and, when signed in, the bearer (all via `ApiClient`), never
   the Gemini key — this endpoint does not read it. The
   server answers with the token it counts against: the same one, or a fresh
   one when ours was missing or invalid. Whatever it says is written back to
   the store here, so the next `POST /api/runs` carries the token the count
   belongs to.

   Like the capabilities adapter, this normalises rather than casting: the
   banner it feeds is optional chrome, so a malformed body must become an
   error the hook goes quiet on, never a render crash on the intake. */


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
  constructor(
    private readonly client: ApiClient,
    private readonly deviceTokenStore: DeviceTokenStore
  ) {}

  async fetchStatus(): Promise<FreeRunsStatus> {
    const token = this.deviceTokenStore.get();
    const res = await this.client.send("/api/free-runs");
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
