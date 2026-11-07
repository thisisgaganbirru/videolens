"use client";

import { useId, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Check, Eye, EyeOff } from "lucide-react";
import { useGeminiApiKey } from "@/application/useGeminiApiKey";
import { isNoticeable } from "@/application/useCapabilities";
import { CapabilityCallout } from "@/components/CapabilityNotice";
import AppBackLink from "@/components/AppBackLink";
import type { Capability } from "@/domain/entities";

/* Hallmark · theme: editorial · page: API key
 * (design/phase4-boards/ApiKey.png, ApiKeyWeb.png, ApiKeyMobile.png)
 * states: field default · hover · focus · show/hide · empty-save error ·
 *         unsaved · saved · removed · budget notice
 *
 * Serif header and lede, one white card holding the key (field + show/hide,
 * the transport sentence, Save / Remove and a status pill), then a tinted
 * "Where to get a key" panel. On phones the status pill wraps under the
 * buttons, as the Web/Mobile boards draw it.
 *
 * The lede is the boards' verbatim since Phase 5b, when the per-device daily
 * free-run allowance (GET /api/free-runs) made "You get a few free runs" true.
 * Copy departs from the boards in one place, for truth: the transport sentence
 * is the phone boards' version on every size, because the desktop board's "We
 * never store it on a server" is not quite true — in distributed mode the key
 * waits in a single-use Redis entry until the worker picks the run up.
 *
 * `budgetCapability` is the deployment's `daily_budget` row, passed down from
 * `HomeScreen` (one /api/capabilities fetch per app load). It is surfaced here
 * and nowhere else because this page is the *answer* to it: an exhausted
 * shared budget does not stop a bring-your-own-key run. It renders the
 * backend's own sentence with no lead, as everywhere else. */

const AI_STUDIO_URL = "https://aistudio.google.com/apikey";

export default function ApiKeyPanel({
  budgetCapability,
}: {
  budgetCapability?: Capability | null;
}) {
  const { value, stored, saved, update, save, clear } = useGeminiApiKey();
  const [revealed, setRevealed] = useState(false);
  const [emptyError, setEmptyError] = useState(false);
  const fieldRef = useRef<HTMLInputElement>(null);
  const fieldId = useId();
  const helpId = useId();
  const errorId = useId();

  const budgetNotice =
    budgetCapability && isNoticeable(budgetCapability.state) ? budgetCapability : null;

  const hasStored = stored !== "";
  const dirty = value.trim() !== stored;

  /* Saving an empty field is a no-op, not a silent Remove: Remove is its own
     button. Same pattern as the intake's empty submit — the button stays
     enabled, says what is missing, and puts the cursor where it is needed. */
  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!value.trim()) {
      setEmptyError(true);
      fieldRef.current?.focus();
      return;
    }
    setEmptyError(false);
    setRevealed(false);
    save();
  };

  const handleRemove = () => {
    setEmptyError(false);
    setRevealed(false);
    clear();
    fieldRef.current?.focus();
  };

  /* One status line, three things it can say. Rendered inside a live region
     that always exists, so the change is announced. */
  let status: ReactNode = null;
  if (hasStored && !dirty) {
    status = (
      <span className="key-status" data-tone="saved">
        <Check aria-hidden="true" />
        Saved on this device
      </span>
    );
  } else if (!hasStored && saved) {
    status = <span className="key-status">Removed from this device</span>;
  } else if (dirty && value.trim()) {
    status = <span className="key-status">Not saved yet</span>;
  }

  return (
    <div className="key-page">
      <AppBackLink />
      <header className="view-head">
        <h1 className="view-title">API key</h1>
        <p className="view-lede">
          Optional. You get a few free runs. Add your own Gemini key to keep going. It is stored in
          this browser only.
        </p>
      </header>

      {budgetNotice && (
        <div className="cap-panel-note key-notice">
          <CapabilityCallout capability={budgetNotice} />
        </div>
      )}

      <form className="key-card" onSubmit={handleSubmit} noValidate>
        <label htmlFor={fieldId} className="key-label">
          Gemini API key
        </label>
        <div className="key-row">
          <input
            ref={fieldRef}
            id={fieldId}
            type={revealed ? "text" : "password"}
            value={value}
            onChange={(event) => {
              setEmptyError(false);
              update(event.target.value);
            }}
            placeholder="Paste your key"
            autoComplete="off"
            autoCapitalize="off"
            autoCorrect="off"
            spellCheck={false}
            className="field key-field"
            aria-describedby={emptyError ? `${errorId} ${helpId}` : helpId}
            aria-invalid={emptyError || undefined}
          />
          <button
            type="button"
            className="key-reveal"
            aria-pressed={revealed}
            aria-controls={fieldId}
            aria-label={revealed ? "Hide key" : "Show key"}
            onClick={() => setRevealed((open) => !open)}
          >
            {revealed ? <EyeOff aria-hidden="true" /> : <Eye aria-hidden="true" />}
          </button>
        </div>
        {emptyError && (
          <p id={errorId} className="error-note key-error">
            Paste your key first, then save it.
          </p>
        )}
        {/* The transport statement is the point of this page, not filler: it
            is what makes pasting a key here a reasonable thing to do. True as
            written since 2026-11-01, when runsGateway stopped attaching the key
            to polls and history — it travels only with POST /api/runs. */}
        <p id={helpId} className="key-help">
          Your key is stored in this browser. It is sent with your own runs and held briefly on the
          server while a run is processed.
        </p>
        <div className="key-actions">
          <button type="submit" className="btn btn-primary btn-pill">
            Save key
          </button>
          {hasStored && (
            <button type="button" className="btn btn-secondary btn-pill key-remove" onClick={handleRemove}>
              Remove key
            </button>
          )}
          <p role="status" className="key-status-slot">
            {status}
          </p>
        </div>
      </form>

      <section className="key-guide" aria-labelledby="key-guide-title">
        <h2 id="key-guide-title" className="key-guide-title">
          Where to get a key
        </h2>
        <ol className="key-steps">
          <li>Open Google AI Studio and sign in.</li>
          <li>Choose Get API key, then Create API key.</li>
          <li>Paste it above and press Save key.</li>
        </ol>
        <a href={AI_STUDIO_URL} target="_blank" rel="noopener noreferrer" className="key-guide-link">
          Open Google AI Studio
          <span className="sr-only"> (opens in a new tab)</span>
        </a>
      </section>
    </div>
  );
}
