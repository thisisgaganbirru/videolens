import type { Capability, CapabilityReport } from "@/domain/entities";
import { ApiError, NetworkError } from "@/domain/errors";
import type { CapabilitiesGateway } from "@/domain/ports";
import { API_BASE_URL } from "./apiBase";

/* `GET /api/capabilities` — the deployment describing itself. See
   docs/backend/capabilities.md.

   Two things about this endpoint shape the adapter:

   - **It always answers 200.** A `degraded` or `unavailable` body is the
     payload, not an error, so `res.ok` is not the success test here the way it
     is in `runsGateway`. Only a transport failure or an unreadable body is a
     failure. A non-200 means something other than this endpoint answered (a
     proxy, a 404 from an older backend), which is genuinely a failure.
   - **It carries no caller identity.** No `X-Client-ID`, no BYOK header. The
     answer is about the server, and sending the user's key to a health
     endpoint would be a gratuitous extra place for it to travel. */

const UNREACHABLE = "Can't reach the server. It may be offline, or your connection dropped.";
const UNREADABLE = "The server replied with something this app could not read.";

/* Unlike `runsGateway`'s `parse<T>`, which casts and trusts, this normalises.
   The difference is deliberate and is a direct consequence of what the caller
   promises: missing health information must never block the app, so this must
   not be able to hand `useCapabilities` a `capabilities` that is `undefined`
   and turn a health-reporting feature into a render crash on the intake
   screen. A run response that lies is a bug worth surfacing; a health response
   that lies must degrade to "no health information". */
function normaliseCapability(raw: unknown): Capability | null {
  if (typeof raw !== "object" || raw === null) return null;
  const row = raw as Record<string, unknown>;
  if (typeof row.name !== "string" || row.name === "") return null;
  return {
    name: row.name,
    /* Not narrowed to the four known states on purpose: a row reporting a
       state this build has never heard of still gets rendered, neutrally,
       rather than being dropped. See `domain/entities.ts`. */
    state: typeof row.state === "string" ? row.state : "",
    detail: typeof row.detail === "string" ? row.detail : "",
    /* Anything that is not literally `true` is treated as unprobed. The
       failure this endpoint exists to prevent is claiming verification that
       never happened, so the ambiguous case has to fall on the honest side. */
    probed: row.probed === true,
  };
}

function normaliseReport(raw: unknown): CapabilityReport {
  const body = (typeof raw === "object" && raw !== null ? raw : {}) as Record<string, unknown>;
  const rows = Array.isArray(body.capabilities) ? body.capabilities : [];
  return {
    state: typeof body.state === "string" ? body.state : "",
    mode: typeof body.mode === "string" ? body.mode : "",
    capabilities: rows.map(normaliseCapability).filter((row): row is Capability => row !== null),
  };
}

export class FetchCapabilitiesGateway implements CapabilitiesGateway {
  async fetchReport(): Promise<CapabilityReport> {
    let res: Response;
    try {
      res = await fetch(`${API_BASE_URL}/api/capabilities`);
    } catch {
      throw new NetworkError(UNREACHABLE);
    }

    if (!res.ok) throw new ApiError(`Could not read capabilities (${res.status})`);

    try {
      return normaliseReport(await res.json());
    } catch {
      throw new ApiError(UNREADABLE);
    }
  }
}
