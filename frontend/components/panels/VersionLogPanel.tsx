"use client";

import { ArrowUpRight } from "lucide-react";
import { useVersionLog } from "@/application/useVersionLog";
import AppBackLink from "@/components/AppBackLink";
import { formatDay } from "@/components/format";
import { orderReleases, releaseSubtitle, releaseVersion } from "@/components/releases";

/* Hallmark · theme: editorial · page: Releases
 * (design/phase4-boards/Releases.png, ReleasesWeb.png, ReleasesMobile.png)
 * states: loading · error + retry · empty · list · link hover · link focus
 *
 * Serif header, a lede naming the running version, then one white card per
 * release: serif "Version X.Y.Z", a Latest pill on the newest, the date. The
 * boards draw bullet notes in each card; `/api/releases` carries no release
 * body (name, tag, date, url only), so the card shows the release name when
 * it says more than the version, and links to the full notes on GitHub
 * rather than inventing bullets.
 *
 * Order and "Latest" are decided here, not trusted from the wire: the backend
 * passes GitHub's order through, so `orderReleases` sorts newest first by
 * publish date (version as the tie-break) before the first card is badged. */

/* Baked in at build time from package.json by next.config.mjs — the same
   number Android's versionName reads. Absent (an unusual build), the lede just
   drops its second sentence rather than claiming a version. */
const APP_VERSION = process.env.NEXT_PUBLIC_APP_VERSION;

export default function VersionLogPanel() {
  return (
    <div className="releases">
      <AppBackLink />
      <header className="view-head">
        <h1 className="view-title">Releases</h1>
        <p className="view-lede">
          What changed in each version.
          {APP_VERSION ? ` You are on version ${APP_VERSION}.` : null}
        </p>
      </header>
      <ReleaseList />
    </div>
  );
}

function ReleaseList() {
  const { entries, error, retrying, retry } = useVersionLog();

  /* .error-inline: a panel-scoped failure with a retry, the same object
     HistoryPanel renders for the same fetch-on-mount failure (the release
     fetch fails when the device is offline, and offline ends). `role=alert`
     because there is something to act on. */
  if (error)
    return (
      <div role="alert" className="error-inline view-state">
        <p>{error}</p>
        <button
          type="button"
          onClick={retry}
          className="btn btn-secondary"
          aria-disabled={retrying || undefined}
        >
          {retrying ? "Retrying…" : "Try again"}
        </button>
      </div>
    );
  if (entries === null)
    return (
      <p role="status" className="pending-note view-state">
        Loading releases…
      </p>
    );
  if (entries.length === 0)
    return <p className="pending-note view-state">No releases published yet.</p>;

  const ordered = orderReleases(entries);

  return (
    <ol className="release-list">
      {ordered.map((entry, index) => {
        const version = releaseVersion(entry);
        const subtitle = releaseSubtitle(entry);
        return (
          <li key={entry.tag || entry.url} className="release-card">
            <div className="release-head">
              <h2 className="release-title">{version ? `Version ${version}` : entry.name}</h2>
              {index === 0 ? <span className="release-latest">Latest</span> : null}
              {entry.publishedAt ? (
                <time className="release-date" dateTime={entry.publishedAt}>
                  {formatDay(entry.publishedAt)}
                </time>
              ) : null}
            </div>
            {subtitle ? <p className="release-note">{subtitle}</p> : null}
            {entry.url ? (
              <a
                href={entry.url}
                target="_blank"
                rel="noopener noreferrer"
                className="release-link"
              >
                Read the notes on GitHub
                <ArrowUpRight aria-hidden="true" />
                <span className="sr-only"> (opens in a new tab)</span>
              </a>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}
