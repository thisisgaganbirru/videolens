import type { VersionLogEntry, VersionLogGateway } from "@/domain/ports";
import { API_BASE_URL } from "./apiBase";

/* `GET /api/releases` — this app's own backend, reading GitHub on our behalf.
   See docs/backend/releases.md.

   The repo is private, so an unauthenticated client-side call to GitHub's
   releases API always 404s, and a token cannot ship in client JS. The read has
   to happen somewhere that can hold a credential. It used to happen in CI,
   which committed the answer back to `dev` as `frontend/public/releases.json`
   and served it as a same-origin static asset — and that bot commit is the
   thing this endpoint exists to remove. A `GITHUB_TOKEN` push starts no
   workflow, so Railway's "Wait for CI" either let it deploy ungated (no PR
   open) or refused to deploy at all (PR open, checks stuck at
   `action_required`); see docs/railway-environments.md. Reading GitHub
   server-side keeps the token on the server and stops anything writing to git.

   Two consequences for this adapter:

   - **The call is cross-origin now**, to the backend rather than to our own
     origin, so it depends on the backend's `ALLOWED_ORIGINS` the same way
     `runsGateway` and `capabilitiesGateway` already do.
   - **An empty list is a valid answer, not a failure.** A backend with no
     GitHub token configured returns `{"releases": []}`, and the panel renders
     its empty state — exactly what the static file did before CI first wrote
     to it. Only a transport failure or a non-2xx is an error. */

/* The wire shape is snake_case; `VersionLogEntry` is camelCase. Mapping here is
   the whole reason this is an adapter and not a bare `fetch` in the hook —
   `domain/` never sees the API's field names. */
type ReleaseRow = { name: string; tag: string; published_at: string; url: string };
type ReleaseIndex = { releases: ReleaseRow[] };

export class FetchVersionLogGateway implements VersionLogGateway {
  async fetchEntries(): Promise<VersionLogEntry[]> {
    const res = await fetch(`${API_BASE_URL}/api/releases`);
    if (!res.ok) throw new Error(`Could not fetch version log (${res.status})`);
    const index: ReleaseIndex = await res.json();
    /* A body without a `releases` array is a backend bug, and the honest
       rendering of it is "nothing to show" rather than a red error region the
       user can only respond to by retrying something that will fail again. */
    if (!Array.isArray(index?.releases)) return [];
    return index.releases.map((row) => ({
      name: row.name,
      tag: row.tag,
      publishedAt: row.published_at,
      url: row.url,
    }));
  }
}
