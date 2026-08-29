"use client";

import { useId, useState } from "react";
import { ChevronDown } from "lucide-react";
import type { Capability, CapabilityReport } from "@/domain/entities";

/* Hallmark · theme: Terminal (locked) · component-scope
 * states: default · hover · focus-visible · active · expanded
 *   (no disabled / loading / error / success — this is a pure local toggle
 *   over data that has already arrived; there is nothing for it to await and
 *   nothing it can reject)
 *
 * The deployment saying which of its parts currently work, shown only when
 * some of them don't. Rendered above the intake so the answer arrives *before*
 * the upload, which is the entire reason the endpoint exists — today a user
 * with a stale yt-dlp uploads, waits, and is told "Media analysis failed.
 * Please try again."
 *
 * Deliberately *not* a fifth nav tab and not a banner. A tab is permanent
 * chrome that would sit there advertising a health check on a healthy app; a
 * banner is the loudest object in the shell and `UpdateBanner` already owns
 * that slot. A collapsed line above the form is read on the way to the field
 * and costs one line of height when there is something to say and nothing at
 * all when there isn't.
 */

type StateStyle = {
  /** The word shown in the row. Not always the raw state — see `disabled`. */
  word: string;
  /** Which severity bucket the CSS should paint. */
  tone: "ok" | "warn" | "bad" | "off";
};

/* `disabled` is renamed and toned as `off`, never as a fault. An unconfigured
   optional dependency is deployment shape — object storage unconfigured in
   local dev is the normal case, not a broken one — and the backend already
   excludes it from the overall state. Rendering it in danger ink would
   reintroduce, in the UI, exactly the lie the backend took care to avoid. */
const STATE_STYLES: Record<string, StateStyle> = {
  ok: { word: "ok", tone: "ok" },
  degraded: { word: "degraded", tone: "warn" },
  unavailable: { word: "unavailable", tone: "bad" },
  disabled: { word: "not configured", tone: "off" },
};

/* A state this build has never seen is shown as itself in neutral ink, not
   dropped and not guessed at. Dropping it would make a report about honesty
   quietly incomplete the first time the backend adds a state. */
function styleFor(state: string): StateStyle {
  return STATE_STYLES[state] ?? { word: state || "unknown", tone: "off" };
}

/* The backend's names are already the human labels once the underscores go:
   `url_download` → `url download`. So there is no lookup table to fall out of
   date, and a capability added server-side renders correctly on an old build
   instead of appearing as a blank row. */
function label(name: string): string {
  return name.replace(/_/g, " ");
}

function namesIn(rows: Capability[], state: string): string {
  return rows
    .filter((row) => row.state === state)
    .map((row) => label(row.name))
    .join(", ");
}

/**
 * One capability's consequence, at the place where it changes what the user
 * should do: `url_download` next to the URL field, `daily_budget` in the API
 * key panel. Same left-ruled, boxless object as the strip above, minus the
 * disclosure — a single row has nothing to disclose.
 *
 * The backend's own `detail` is rendered verbatim, on the same rule
 * `HistoryPanel` follows for gateway errors: the server wrote the specific
 * sentence, so a caller paraphrasing it can only make it less accurate. The
 * `lead` is the one thing the frontend adds, because the row's *name* does not
 * survive the move out of the table — "the cookie file is missing" needs
 * "URL runs may fail" in front of it to mean anything beside a URL field.
 */
export function CapabilityCallout({
  capability,
  lead,
}: {
  capability: Capability;
  lead?: string;
}) {
  const tone = capability.state === "unavailable" ? "bad" : "warn";
  const detail = capability.detail || `${label(capability.name)} is ${styleFor(capability.state).word}.`;

  return (
    <div className="cap-notice" data-state={capability.state}>
      <p className="cap-line" data-tone={tone}>
        {lead ? (
          <>
            <strong>{lead}</strong> — {detail}
          </>
        ) : (
          detail
        )}
      </p>
    </div>
  );
}

export default function CapabilityNotice({ report }: { report: CapabilityReport }) {
  const [open, setOpen] = useState(false);
  const detailId = useId();

  const unavailable = namesIn(report.capabilities, "unavailable");
  const degraded = namesIn(report.capabilities, "degraded");

  /* One line per severity rather than one prose sentence. A status readout is
     what this is, and in a monospace theme at 34rem a sentence long enough to
     name three capabilities wraps to three lines anyway — this says the same
     thing in less space and scans without being read. */
  const lines: { tone: "bad" | "warn"; text: string }[] = [];
  if (unavailable) lines.push({ tone: "bad", text: `unavailable — ${unavailable}` });
  if (degraded) lines.push({ tone: "warn", text: `degraded — ${degraded}` });

  /* The overall state said something is wrong but no row admits to it: a
     backend newer than this build. Say so plainly rather than rendering an
     empty warning box. */
  if (lines.length === 0) {
    lines.push({ tone: "warn", text: `service state — ${report.state}` });
  }

  return (
    <div className="cap-notice" data-state={report.state}>
      <button
        type="button"
        className="cap-summary"
        aria-expanded={open}
        aria-controls={detailId}
        onClick={() => setOpen((wasOpen) => !wasOpen)}
      >
        <span className="cap-summary-lines">
          {lines.map((line) => (
            <span key={line.text} className="cap-line" data-tone={line.tone}>
              {line.text}
            </span>
          ))}
        </span>
        <span className="cap-more">
          {open ? "hide" : "details"}
          <ChevronDown className="cap-chevron" aria-hidden="true" />
        </span>
      </button>

      {/* Rendered even while collapsed, hidden with `hidden`, so `aria-controls`
          always points at something that exists. */}
      <div className="cap-detail" id={detailId} hidden={!open}>
        <ul className="cap-rows">
          {report.capabilities.map((row) => {
            const style = styleFor(row.state);
            return (
              <li key={row.name} className="cap-row" data-tone={style.tone}>
                <span className="cap-row-head">
                  <span className="cap-name">{label(row.name)}</span>
                  <span className="cap-state">{style.word}</span>
                  {/* The honest core of the report: this row was read off
                      configuration, not checked. It is a visible tag rather
                      than a tooltip or a title attribute because a caveat you
                      have to hover to find is a caveat that was hidden. */}
                  {!row.probed && <span className="cap-unverified">unverified</span>}
                </span>
                {row.detail && <span className="cap-row-detail">{row.detail}</span>}
              </li>
            );
          })}
        </ul>
        <p className="cap-legend">
          <strong>unverified</strong> — read from this deployment&apos;s configuration and not
          checked against the live dependency.
        </p>
      </div>
    </div>
  );
}
