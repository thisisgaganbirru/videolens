import { App } from "@capacitor/app";
import { Capacitor } from "@capacitor/core";

// Not distributed through Play Store, so nothing else checks for updates.
// GitHub's own "latest release" shortcuts skip prereleases, and every build
// here is published as one, so the release list is queried directly and
// sorted by creation date instead.
const RELEASES_API_URL = "https://api.github.com/repos/thisisgaganbirru/videolens/releases?per_page=5";
const VERSION_MANIFEST_ASSET_NAME = "version.json";

export type UpdateInfo = {
  versionName: string;
  releaseUrl: string;
};

type ReleaseAsset = { name: string; browser_download_url: string };
type Release = { assets: ReleaseAsset[]; html_url: string; draft: boolean; created_at: string };
type VersionManifest = { versionCode: number; versionName: string; releaseUrl?: string };

export async function checkForUpdate(): Promise<UpdateInfo | null> {
  if (!Capacitor.isNativePlatform() || Capacitor.getPlatform() !== "android") return null;

  try {
    const info = await App.getInfo();
    const currentBuild = Number(info.build);
    if (!Number.isFinite(currentBuild)) return null;

    const releasesRes = await fetch(RELEASES_API_URL, {
      headers: { Accept: "application/vnd.github+json" },
    });
    if (!releasesRes.ok) return null;
    const releases: Release[] = await releasesRes.json();

    const latest = releases
      .filter((release) => !release.draft)
      .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
      .find((release) => release.assets.some((asset) => asset.name === VERSION_MANIFEST_ASSET_NAME));
    const manifestAsset = latest?.assets.find((asset) => asset.name === VERSION_MANIFEST_ASSET_NAME);
    if (!latest || !manifestAsset) return null;

    const manifestRes = await fetch(manifestAsset.browser_download_url);
    if (!manifestRes.ok) return null;
    const manifest: VersionManifest = await manifestRes.json();

    if (!(manifest.versionCode > currentBuild)) return null;

    return { versionName: manifest.versionName, releaseUrl: manifest.releaseUrl || latest.html_url };
  } catch {
    // Update checks are best-effort - never block or break the app over one.
    return null;
  }
}
