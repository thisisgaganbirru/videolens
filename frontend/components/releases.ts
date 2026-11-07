import type { VersionLogEntry } from "@/domain/ports";

/* Pure helpers for the Releases page — no React, no fetch.
 *
 * Tags follow the scheme the backend parses for update checks
 * (`v2.1.1-build412`, optionally `dev-` prefixed); a bare `v2.1.1` or a name
 * like "VideoLens 2.1.1" also yields a version. Anything else has no version
 * and the card falls back to the release name. */

const VERSION = /(\d+)\.(\d+)\.(\d+)/;

export function releaseVersion(entry: VersionLogEntry): string | null {
  const fromTag = /^(?:dev-)?v?(\d+\.\d+\.\d+)/.exec(entry.tag ?? "");
  if (fromTag) return fromTag[1];
  const fromName = VERSION.exec(entry.name ?? "");
  return fromName ? fromName[0] : null;
}

function versionParts(entry: VersionLogEntry): [number, number, number] | null {
  const v = releaseVersion(entry);
  if (!v) return null;
  const [a, b, c] = v.split(".").map(Number);
  return [a, b, c];
}

function time(entry: VersionLogEntry): number {
  const t = Date.parse(entry.publishedAt);
  return Number.isFinite(t) ? t : Number.NEGATIVE_INFINITY;
}

/** Newest first: publish date, then version, then the order the API gave. */
export function orderReleases(entries: VersionLogEntry[]): VersionLogEntry[] {
  return entries
    .map((entry, index) => ({ entry, index }))
    .sort((x, y) => {
      const tx = time(x.entry);
      const ty = time(y.entry);
      if (tx !== ty) return ty > tx ? 1 : -1; // undated rows sink
      const vx = versionParts(x.entry);
      const vy = versionParts(y.entry);
      if (vx && vy) {
        for (let i = 0; i < 3; i += 1) if (vx[i] !== vy[i]) return vy[i] - vx[i];
      }
      return x.index - y.index;
    })
    .map(({ entry }) => entry);
}

/** The release name, only when it says more than the version already shown. */
export function releaseSubtitle(entry: VersionLogEntry): string | null {
  const name = (entry.name ?? "").trim();
  const version = releaseVersion(entry);
  if (!name || !version) return null;
  const rest = name
    .replace(/^videolens(\s+ai)?/i, "")
    .replace(/^\s*(version\s+)?v?\d+\.\d+\.\d+(-build\d+)?/i, "")
    .replace(/^[\s:—–-]+/, "")
    .trim();
  if (!rest) return null;
  return rest.charAt(0).toUpperCase() + rest.slice(1);
}
