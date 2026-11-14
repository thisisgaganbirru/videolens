"use client";

import { useId, useRef, useState, type FormEvent, type MouseEvent, type ReactNode } from "react";
import { Check, Eye, EyeOff } from "lucide-react";
import { useGeminiApiKey } from "@/application/useGeminiApiKey";
import { isNoticeable } from "@/application/useCapabilities";
import { CapabilityCallout } from "@/components/CapabilityNotice";
import AppBackLink from "@/components/AppBackLink";
import { isPlainLeftClick } from "@/components/navClick";
import { goToMainTab, mainTabHref } from "@/application/useMainTab";
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
 * The help line under the field is the owner-approved consent wording
 * (2026-11-13), with links to Terms and Privacy; it replaced the phone
 * boards' "held briefly on the server" sentence.
 *
 * `budgetCapability` is the deployment's `daily_budget` row, passed down from
 * `HomeScreen` (one /api/capabilities fetch per app load). It is surfaced here
 * and nowhere else because this page is the *answer* to it: an exhausted
 * shared budget does not stop a bring-your-own-key run. It renders the
 * backend's own sentence with no lead, as everywhere else. */

const AI_STUDIO_URL = "https://aistudio.google.com/apikey";

function openAccount(event: MouseEvent<HTMLAnchorElement>) {
  if (!isPlainLeftClick(event)) return;
  event.preventDefault();
  goToMainTab("account");
}

export default function ApiKeyPanel({
  budgetCapability,
  signInForMinutes = null,
  signInPending = false,
  signInStandInMinutes = 10,
}: {
  budgetCapability?: Capability | null;
  /** Minutes a signed-in person on their own key may send, offered only
   *  where sign-in works and nobody is signed in, and only when the server
   *  reports a larger tier (HomeScreen decides). Null hides the line. */
  signInForMinutes?: number | null;
  /** Whether the sign-in line applies is not known yet (session, the
   *  capabilities report or `/api/limits` still on its way). Its space is
   *  then held so the actions and the guide do not drop when it lands. */
  signInPending?: boolean;
  /** Minutes the held line is sized with; never seen. */
  signInStandInMinutes?: number;
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
        Saved in this browser
      </span>
    );
  } else if (!hasStored && saved) {
    status = <span className="key-status">Removed from this browser</span>;
  } else if (dirty && value.trim()) {
    status = <span className="key-status">Not saved yet</span>;
  }

  return (
    <div className="key-page">
      <AppBackLink />
      <header className="view-head">
        <h1 className="view-title">Gemini key</h1>
        <p className="view-lede">
          Optional. VideoLens works without a key. Runs on your own Gemini key don&apos;t count
          toward your daily runs. The key is saved in this browser only.
        </p>
      </header>

      {budgetNotice && (
        <div className="cap-panel-note key-notice">
          <CapabilityCallout capability={budgetNotice} />
        </div>
      )}

      <form className="key-card" onSubmit={handleSubmit} noValidate>
        <label htmlFor={fieldId} className="key-label">
          Gemini key
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
        {/* The transport and consent statement is the point of this page,
            not filler: it is what makes pasting a key here a reasonable thing
            to do. Owner-approved wording (2026-11-13), replacing the earlier
            "held briefly on the server" line; the key travels only with
            POST /api/runs (runsGateway, since 2026-11-01). Saving is the
            agreement: no checkbox, by the owner's choice. */}
        <p id={helpId} className="key-help">
          Your key is saved only on this device. VideoLens passes it to Google for your own runs
          and never stores it. You&apos;re responsible for your key and any usage on your Google
          account. By saving a key you agree to the{" "}
          <a className="text-link" href="/terms">
            Terms
          </a>{" "}
          and{" "}
          <a className="text-link" href="/privacy">
            Privacy Policy
          </a>
          .
        </p>
        {/* Same rule as the nav's Account tab: only where sign-in works and
            nobody is signed in. States what the longer tier is, never that
            signing in makes the key safer. */}
        {signInForMinutes ? (
          <p className="key-help key-signin">
            Signed in with your own key, you can analyze videos up to {signInForMinutes} minutes.{" "}
            <a className="text-link" href={mainTabHref("account")} onClick={openAccount}>
              Sign in
            </a>
          </p>
        ) : signInPending ? (
          /* Same sentence, same box, held unseen while it is not known
             whether the line applies (UX fix follow-up: it used to arrive
             late and push Save and the guide down). Not a link, not read. */
          <p className="key-help key-signin key-signin-ghost" aria-hidden="true" inert>
            Signed in with your own key, you can analyze videos up to {signInStandInMinutes} minutes.{" "}
            <span className="text-link">Sign in</span>
          </p>
        ) : null}
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
        {/* Damage limit, not a promise: the key stays readable to anything
            running in this page, so the cheap protection is a key that can
            only spend a little. Wording avoids naming an AI Studio menu that
            may move. */}
        <p className="key-guide-note">
          Use a key made only for VideoLens, with a spending limit set in Google AI Studio, so a
          leaked key costs little.
        </p>
        <a href={AI_STUDIO_URL} target="_blank" rel="noopener noreferrer" className="key-guide-link">
          Open Google AI Studio
          <span className="sr-only"> (opens in a new tab)</span>
        </a>
      </section>
    </div>
  );
}
