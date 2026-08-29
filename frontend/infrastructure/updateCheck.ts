import { App } from "@capacitor/app";
import { Capacitor } from "@capacitor/core";
import type { UpdateChecker, UpdateInfo } from "@/domain/ports";

// Not distributed through Play Store, so nothing else checks for updates.
//
// This reads a manifest the CI pipeline publishes to the deployed web app
// (.github/workflows/android-development-build.yml, "Update release
// manifest"), not GitHub's API. The repo is private: an unauthenticated
// client-side call to api.github.com always 404s, and a token cannot safely
// live in client-side JS - the same constraint that already moved the
// Releases tab onto a static file (infrastructure/versionLogGateway.ts).
// Calling the API here silently disabled update notifications entirely,
// because a 404 is indistinguishable from "no update" in this code path.
//
// The URL is absolute and points at the deployed web app on purpose. Next
// inlines NEXT_PUBLIC_* at build time and `public/` ships inside the APK, so
// a relative "/version.json" would read the copy frozen into this build -
// which by definition can never describe a build newer than itself.
const WEB_BASE_URL = process.env.NEXT_PUBLIC_WEB_BASE_URL;
const VERSION_MANIFEST_PATH = "/version.json";

type VersionManifest = { versionCode: number; versionName: string; releaseUrl?: string };

export class GithubUpdateChecker implements UpdateChecker {
  async checkForUpdate(): Promise<UpdateInfo | null> {
    if (!Capacitor.isNativePlatform() || Capacitor.getPlatform() !== "android") return null;
    // Without a deployed origin to ask there is no way to learn about a newer
    // build; no-op rather than fall back to this APK's own frozen copy.
    if (!WEB_BASE_URL) return null;

    try {
      const info = await App.getInfo();
      const currentBuild = Number(info.build);
      if (!Number.isFinite(currentBuild)) return null;

      const manifestRes = await fetch(`${WEB_BASE_URL}${VERSION_MANIFEST_PATH}`, {
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (!manifestRes.ok) return null;
      const manifest: VersionManifest = await manifestRes.json();

      if (!Number.isFinite(manifest.versionCode)) return null;
      if (!(manifest.versionCode > currentBuild)) return null;
      if (!manifest.releaseUrl) return null;

      return { versionName: manifest.versionName, releaseUrl: manifest.releaseUrl };
    } catch {
      // Update checks are best-effort - never block or break the app over one.
      return null;
    }
  }
}
