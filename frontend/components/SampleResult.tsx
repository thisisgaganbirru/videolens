"use client";

import { useRef, useState, type KeyboardEvent } from "react";

/* Hallmark · component: tabs (sample result card) · genre: editorial · theme: custom (app/tokens.css)
 * states: default · hover · focus-visible · selected — reuses .tab-list/.tab/.panel from the results view
 *
 * The card beside the landing headline (Landing.png, LandingWeb.png): what a
 * finished run looks like, labelled "Sample result" so nobody mistakes it for
 * a real one. The four tabs are the results view's four, in its order, with
 * Notes selected as drawn. The content is written for the card, not taken from
 * a real run, and claims nothing beyond what a result actually contains.
 *
 * Real tabs (roving tabindex, arrow keys, Home/End) because they look like
 * tabs: a row that looks pressable and does nothing is worse than no row. */

type SampleTab = "tldr" | "notes" | "transcript" | "onscreen";

const TABS: { id: SampleTab; label: string }[] = [
  { id: "tldr", label: "TL;DR" },
  { id: "notes", label: "Notes" },
  { id: "transcript", label: "Transcript" },
  { id: "onscreen", label: "On-screen" },
];

export default function SampleResult() {
  const [active, setActive] = useState<SampleTab>("notes");
  const tabRefs = useRef<Record<SampleTab, HTMLButtonElement | null>>({
    tldr: null,
    notes: null,
    transcript: null,
    onscreen: null,
  });

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const index = TABS.findIndex((tab) => tab.id === active);
    let next = index;
    if (event.key === "ArrowRight") next = (index + 1) % TABS.length;
    else if (event.key === "ArrowLeft") next = (index - 1 + TABS.length) % TABS.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = TABS.length - 1;
    else return;
    event.preventDefault();
    const id = TABS[next].id;
    setActive(id);
    tabRefs.current[id]?.focus();
  };

  return (
    <article className="sample-card" aria-labelledby="sample-title">
      <p className="sample-label">Sample result</p>
      <h2 id="sample-title" className="sample-title">
        A week of lunches, cooked in one hour
      </h2>

      <div className="tab-list sample-tabs" role="tablist" aria-label="Sample result" onKeyDown={onKeyDown}>
        {TABS.map((tab) => (
          <button
            key={tab.id}
            ref={(node) => {
              tabRefs.current[tab.id] = node;
            }}
            type="button"
            role="tab"
            id={`sample-tab-${tab.id}`}
            className="tab"
            aria-selected={active === tab.id}
            aria-controls={`sample-panel-${tab.id}`}
            tabIndex={active === tab.id ? 0 : -1}
            onClick={() => setActive(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div
        role="tabpanel"
        id="sample-panel-tldr"
        aria-labelledby="sample-tab-tldr"
        className="panel sample-panel"
        data-active={active === "tldr"}
        hidden={active !== "tldr"}
      >
        <div className="takeaway">
          <span className="takeaway-label">Key takeaway</span>
          <p className="takeaway-text">One Sunday session of cooking covers a week of lunches.</p>
        </div>
      </div>

      <div
        role="tabpanel"
        id="sample-panel-notes"
        aria-labelledby="sample-tab-notes"
        className="panel sample-panel"
        data-active={active === "notes"}
        hidden={active !== "notes"}
      >
        <p className="sample-text">
          Cook one grain, one protein and two vegetables in a single Sunday session, then box them up
          and keep the sauces separate.
        </p>
        <div className="takeaway">
          <span className="takeaway-label">Key takeaway</span>
          <p className="takeaway-text">Cook components, not meals.</p>
        </div>
      </div>

      <div
        role="tabpanel"
        id="sample-panel-transcript"
        aria-labelledby="sample-tab-transcript"
        className="panel sample-panel"
        data-active={active === "transcript"}
        hidden={active !== "transcript"}
      >
        <ol className="sample-lines">
          <li>
            <span className="sample-time">0:00</span>
            <span>Here is how I cook a whole week of lunches in about an hour.</span>
          </li>
          <li>
            <span className="sample-time">0:07</span>
            <span>Start the rice first, because it takes the longest.</span>
          </li>
          <li>
            <span className="sample-time">0:15</span>
            <span>While it cooks, the chickpeas go in the oven.</span>
          </li>
        </ol>
      </div>

      <div
        role="tabpanel"
        id="sample-panel-onscreen"
        aria-labelledby="sample-tab-onscreen"
        className="panel sample-panel"
        data-active={active === "onscreen"}
        hidden={active !== "onscreen"}
      >
        <ol className="sample-lines">
          <li>
            <span className="sample-time">0:03</span>
            <span>SUNDAY PREP · 60 MIN</span>
          </li>
          <li>
            <span className="sample-time">0:21</span>
            <span>Rice · chickpeas · broccoli · peppers</span>
          </li>
        </ol>
      </div>
    </article>
  );
}
