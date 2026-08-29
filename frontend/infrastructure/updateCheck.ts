import { App } from "@capacitor/app";
import { Capacitor } from "@capacitor/core";
import type { UpdateChecker, UpdateInfo } from "@/domain/ports";
import { API_BASE_URL } from "./apiBase";

// Not distributed through Play Store, so nothing else checks for updates.
//
// This asks this app's own backend (`GET /api/releases`, see
// docs/backend/releases.md), never GitHub directly. The repo is private: an
// unauthenticated client-side call to api.github.com always 404s, and a token
// cannot safely live in client-side JS - so the read has to happen somewhere
// that can hold a credential. Calling GitHub's API from here silently disabled
// update notifications entirely, because a 404 is indistinguishable from "no
// update" in this code path.
//
// It used to be CI that held the credential, writing the answer into a static
// `version.json` and committing it back to `dev`. That bot commit is the thing
// the endpoint exists to remove: a `GITHUB_TOKEN` push starts no workflow, so
// Railway's "Wait for CI" either deployed it ungated or refused to deploy at
// all, depending on whether a PR was open (docs/railway-environments.md).
//
// The origin is absolute and compiled in at build time
// (NEXT_PUBLIC_API_BASE_URL, which reusable-android-checks.yml passes to
// `android:sync`; Next inlines NEXT_PUBLIC_* into the export the APK ships).
// It has to be, and it has to point off-device: `public/` ships inside the
// APK, so anything this build carries locally can by definition never describe
// a build newer than itself. There is no guard for an unset origin the way
// there was for the old NEXT_PUBLIC_WEB_BASE_URL, because API_BASE_URL falls
// back to a localhost default rather than to undefined - a misconfigured build
// fails its fetch and lands in the catch below, which is the same no-op.

/* The endpoint answers snake_case. `latest` is null when no release tag
   matches the `dev-v<version>-build<code>` scheme the backend parses, which is
   also what an unconfigured backend returns - both mean "cannot say", and both
   land on the same no-op below. */
type LatestRelease = { version_code: number; version_name: string; url: string };
type ReleaseIndex = { latest?: LatestRelease | null };

export class ApiUpdateChecker implements UpdateChecker {
  async checkForUpdate(): Promise<UpdateInfo | null> {
    if (!Capacitor.isNativePlatform() || Capacitor.getPlatform() !== "android") return null;

    try {
      const info = await App.getInfo();
      const currentBuild = Number(info.build);
      if (!Number.isFinite(currentBuild)) return null;

      const res = await fetch(`${API_BASE_URL}/api/releases`, {
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (!res.ok) return null;
      const index: ReleaseIndex = await res.json();

      const latest = index?.latest;
      if (!latest) return null;
      if (!Number.isFinite(latest.version_code)) return null;
      // Strictly greater: equal is the build already installed, and lower is a
      // rollback the app should not offer to "update" to.
      if (!(latest.version_code > currentBuild)) return null;
      if (!latest.url) return null;

      return { versionName: latest.version_name, releaseUrl: latest.url };
    } catch {
      // Update checks are best-effort - never block or break the app over one.
      return null;
    }
  }
}
