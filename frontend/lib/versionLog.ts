const RELEASES_API_URL = "https://api.github.com/repos/thisisgaganbirru/videolens/releases?per_page=10";

export type VersionLogEntry = {
  name: string;
  tag: string;
  publishedAt: string;
  url: string;
};

type Release = { name: string; tag_name: string; html_url: string; published_at: string; draft: boolean };

export async function fetchVersionLog(): Promise<VersionLogEntry[]> {
  const res = await fetch(RELEASES_API_URL, { headers: { Accept: "application/vnd.github+json" } });
  if (!res.ok) throw new Error(`Could not fetch version log (${res.status})`);
  const releases: Release[] = await res.json();
  return releases
    .filter((release) => !release.draft)
    .sort((a, b) => new Date(b.published_at).getTime() - new Date(a.published_at).getTime())
    .map((release) => ({
      name: release.name || release.tag_name,
      tag: release.tag_name,
      publishedAt: release.published_at,
      url: release.html_url,
    }));
}
