"use client";

import { useId, useState } from "react";
import { ChevronDown } from "lucide-react";
import type { Capability, CapabilityReport } from "@/domain/entities";

/* Hallmark · pre-emit critique: P5 H5 E4 S5 R5 V4 */
/* Hallmark · component: service notice · genre: editorial · theme: custom (owner handoff)
 * states: default · hover · focus-visible · active · expanded
 *   (no disabled / loading / error / success: a local toggle over data that
 *   has already arrived; there is nothing to await and nothing it can reject)
 *
 * The deployment saying which of its parts currently work, shown only when
 * some of them don't, so the answer arrives *before* the upload — which is
 * the reason the endpoint exists.
 *
 * Editorial Phase 2 (2026-11-01): one compact line by default — a status dot,
 * a sentence-case summary, a "Details" toggle — in a quiet surface card with
 * the same edge as `.run-notice`. Opening it lists every row in plain words.
 * Red is used only for what has actually failed (`unavailable`): the dot and
 * the state word, never the whole object. No uppercase, no boxed tags. Where
 * it sits (above "What you get" on a wide screen, above the eyebrow on a
 * phone) is HomeScreen's grid, so it never pushes the intake card down.
 */

type Tone = "ok" | "warn" | "bad" | "off";

/* Sentence-case state words. `disabled` reads as "Not set up" and is toned as
   `off`, never as a fault: an unconfigured optional dependency is deployment
   shape, and the backend already excludes it from the overall state. */
const STATE_WORDS: Record<string, { word: string; tone: Tone }> = {
  ok: { word: "Working", tone: "ok" },
  degraded: { word: "Limited", tone: "warn" },
  unavailable: { word: "Unavailable", tone: "bad" },
  disabled: { word: "Not set up", tone: "off" },
};

/* A state this build has never seen is shown as itself, neutral — not dropped
   and not guessed at. */
function stateFor(state: string): { word: string; tone: Tone } {
  return STATE_WORDS[state] ?? { word: sentence(state || "unknown"), tone: "off" };
}

/* Plain names for the capabilities this build knows. Anything else falls back
   to the backend's own name with the underscores gone, so a capability added
   server-side still renders on an old build instead of as a blank row. */
const NAMES: Record<string, string> = {
  media_tools: "Media processing",
  url_download: "Link downloads",
  analysis_engine: "Analysis",
  run_store: "Run history",
  object_storage: "File storage",
  daily_budget: "Shared daily budget",
};

function sentence(text: string): string {
  const spaced = text.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

function label(name: string): string {
  return NAMES[name] ?? sentence(name);
}

/** "Media processing and link downloads" — the first name keeps its capital. */
function listOf(rows: Capability[], state: string): string {
  const names = rows.filter((row) => row.state === state).map((row) => label(row.name));
  const lowered = names.map((name, i) => (i === 0 ? name : name.charAt(0).toLowerCase() + name.slice(1)));
  if (lowered.length <= 1) return lowered.join("");
  return `${lowered.slice(0, -1).join(", ")} and ${lowered[lowered.length - 1]}`;
}

function lower(text: string): string {
  return text.charAt(0).toLowerCase() + text.slice(1);
}

function count(rows: Capability[], state: string): number {
  return rows.filter((row) => row.state === state).length;
}

/**
 * One capability's consequence at the place where it changes what the user
 * should do: `url_download` under the URL field, `daily_budget` in the API
 * key panel. The backend's own `detail` is rendered verbatim — the server
 * wrote the specific sentence, so paraphrasing it can only make it less
 * accurate. `lead` is the one thing the frontend adds.
 */
export function CapabilityCallout({
  capability,
  lead,
}: {
  capability: Capability;
  lead?: string;
}) {
  const tone = capability.state === "unavailable" ? "bad" : "warn";
  const detail =
    capability.detail || `${label(capability.name)}: ${stateFor(capability.state).word.toLowerCase()}.`;

  return (
    <p className="cap-callout" data-tone={tone}>
      <span className="cap-dot" aria-hidden="true" />
      <span>
        {lead ? (
          <>
            <strong>{lead}.</strong> {detail}
          </>
        ) : (
          detail
        )}
      </span>
    </p>
  );
}

export default function CapabilityNotice({ report }: { report: CapabilityReport }) {
  const [open, setOpen] = useState(false);
  const detailId = useId();

  const rows = report.capabilities;
  const bad = count(rows, "unavailable");
  const warn = count(rows, "degraded");

  /* Label first ("Unavailable right now: media processing."), so the sentence
     never has to agree a verb with a name it does not control — "link
     downloads" is plural, "media processing" is not, and a capability added
     server-side could be either. What is down comes before what is limited. */
  const parts: string[] = [];
  if (bad) parts.push(`Unavailable right now: ${lower(listOf(rows, "unavailable"))}.`);
  if (warn) parts.push(`Limited: ${lower(listOf(rows, "degraded"))}.`);
  /* The overall state said something is wrong but no row admits to it: a
     backend newer than this build. Say so rather than render an empty notice. */
  if (parts.length === 0) parts.push(`The service reports “${report.state}”.`);

  const tone: Tone = bad ? "bad" : "warn";
  const anyUnchecked = rows.some((row) => !row.probed);

  return (
    <div className="cap-notice" data-tone={tone}>
      <div className="cap-head">
        <span className="cap-dot" aria-hidden="true" />
        <p className="cap-summary-text">{parts.join(" ")}</p>
        <button
          type="button"
          className="cap-toggle"
          aria-expanded={open}
          aria-controls={detailId}
          onClick={() => setOpen((wasOpen) => !wasOpen)}
        >
          {open ? "Hide" : "Details"}
          <ChevronDown className="cap-chevron" aria-hidden="true" />
        </button>
      </div>

      {/* In the DOM while collapsed (hidden), so `aria-controls` always points
          at something that exists. */}
      <div className="cap-detail" id={detailId} hidden={!open}>
        <ul className="cap-rows">
          {rows.map((row) => {
            const state = stateFor(row.state);
            return (
              <li key={row.name} className="cap-row">
                <span className="cap-row-head">
                  <span className="cap-name">{label(row.name)}</span>
                  <span className="cap-state" data-tone={state.tone}>
                    {state.word}
                    {/* Read off configuration, not checked against the live
                        dependency. Inline words rather than a tooltip: a caveat
                        you have to hover to find is a caveat that was hidden. */}
                    {!row.probed && <span className="cap-unchecked"> · not checked</span>}
                  </span>
                </span>
                {row.detail && <span className="cap-row-detail">{row.detail}</span>}
              </li>
            );
          })}
        </ul>
        {anyUnchecked && (
          <p className="cap-legend">
            “Not checked” means read from this server&apos;s settings, not tested against the live
            service.
          </p>
        )}
      </div>
    </div>
  );
}
