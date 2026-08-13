"use client";

import { ExternalLink } from "lucide-react";
import { useGeminiApiKey } from "@/application/useGeminiApiKey";

export default function ApiKeyPanel() {
  const { value, saved, update, save, clear } = useGeminiApiKey();

  return (
    <div className="flex flex-col gap-4 max-w-lg">
      <p className="text-sm leading-6 text-[var(--color-muted)]">
        Optional. Paste your own Gemini API key to use your own quota — it stays on this device and is only sent with your own requests.
      </p>
      <a
        href="https://aistudio.google.com/apikey"
        target="_blank"
        rel="noopener noreferrer"
        className="text-link gap-1.5 self-start text-sm"
      >
        Get a key from Google AI Studio
        <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
      </a>
      <input
        type="password"
        value={value}
        onChange={(event) => update(event.target.value)}
        placeholder="Paste your Gemini API key"
        autoComplete="off"
        spellCheck={false}
        className="field"
      />
      <div className="flex gap-2">
        <button type="button" onClick={save} className="button-primary text-xs px-5 py-2">
          Save
        </button>
        <button type="button" onClick={clear} className="button-secondary text-xs px-5 py-2">
          Clear
        </button>
      </div>
      <p className="text-xs text-[var(--color-faint)]">
        {saved ? "Saved on this device." : "Stored only on this device."}
      </p>
    </div>
  );
}
