"use client";

import { ExternalLink } from "lucide-react";
import { useGeminiApiKey } from "@/application/useGeminiApiKey";

export default function ApiKeyPanel() {
  const { value, saved, update, save, clear } = useGeminiApiKey();

  return (
    <div className="apikey-form">
      {/* The storage and transport statement is the point of this panel, not
          filler — it is what makes pasting a key here a reasonable thing to
          do. It names localStorage and the header by name on purpose. */}
      <p className="card-label mb-1">Optional</p>
      <p className="prose">
        Paste your own Gemini API key to run on your own quota instead of the shared
        one. It is stored only in this browser&apos;s <strong>localStorage</strong> and is sent
        only with your own runs, as an <strong>X-Gemini-Api-Key</strong> header — never written
        to the server.{" "}
        <a
          href="https://aistudio.google.com/apikey"
          target="_blank"
          rel="noopener noreferrer"
          className="text-link gap-1 inline-flex items-center"
        >
          Get a key from Google AI Studio
          <ExternalLink className="h-3 w-3" aria-hidden="true" />
        </a>
      </p>

      <div className="my-[var(--space-md)] flex flex-col items-start gap-1.5">
        <label htmlFor="gemini-api-key" className="card-label !m-0">
          gemini api key
        </label>
        <input
          id="gemini-api-key"
          type="password"
          value={value}
          onChange={(event) => update(event.target.value)}
          placeholder="paste your gemini api key"
          autoComplete="off"
          spellCheck={false}
          className="field"
        />
      </div>

      <div className="apikey-actions">
        <button type="button" onClick={save} className="btn btn-primary">
          save
        </button>
        <button type="button" onClick={clear} className="btn btn-secondary">
          clear
        </button>
      </div>

      <p role="status" className="pending-note mt-[var(--space-xs)]">
        {saved ? "Saved on this device." : "Stored only on this device."}
      </p>
    </div>
  );
}
