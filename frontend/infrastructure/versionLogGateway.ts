import type { VersionLogEntry, VersionLogGateway } from "@/domain/ports";

type ReleaseEntry = { name: string; tag: string; publishedAt: string; url: string };
type ReleaseManifest = { releases: ReleaseEntry[] };

// Reads a static file the CI pipeline maintains (see
// .github/workflows/android-development-build.yml, "Update release
// manifest" step) instead of calling GitHub's API from the browser. The
// repo is private, so an unauthenticated client-side call to GitHub's
// releases API always 404s - this avoids needing any credential at all by
// moving the GitHub read to CI build-time, where the workflow's own ambient
// token already has access, and shipping the result as a same-origin
// static asset.
export class StaticVersionLogGateway implements VersionLogGateway {
  async fetchEntries(): Promise<VersionLogEntry[]> {
    const res = await fetch("/releases.json");
    if (!res.ok) throw new Error(`Could not fetch version log (${res.status})`);
    const manifest: ReleaseManifest = await res.json();
    return manifest.releases;
  }
}
