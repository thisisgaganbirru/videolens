"use client";

import { useEffect, useRef } from "react";
import { BrandMark } from "@/components/AppNav";
import { useWelcome } from "@/application/useFirstRun";

/* Hallmark · component: first-run screen (installed app only) · genre: editorial
 * board: design/shots/WelcomeApp.png — mark, serif headline, lede, three
 * numbered steps, a tint note on the free runs, two full-width pill actions.
 * states: closed · open · button default/hover/focus-visible/active
 *
 * Installed app only: the board is a phone-app board, and in a browser tab the
 * landing page at `/` already does this job. Shown once, then remembered (see
 * useFirstRun / firstRunStore); never on a launch that carried a share or a
 * deep link, and a share that arrives while it is open closes it, so the link
 * is never lost.
 *
 * A native modal <dialog> like the More sheet: the top layer, the app
 * underneath inert, focus held inside, Escape as "skip" (Start analyzing). The
 * tool stays mounted underneath the whole time — that is what lets a share
 * land in the intake while this is up. */

const STEPS = [
  { title: "Paste or drop", text: "A link, or an audio or video file." },
  { title: "Let it read", text: "It listens to the speech and reads the text on screen." },
  { title: "Read and keep", text: "Copy the notes or download them." },
];

export default function Welcome() {
  const { open, dismiss } = useWelcome();
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (open && dialog && !dialog.open) dialog.showModal();
  }, [open]);

  if (!open) return null;

  return (
    <dialog
      ref={ref}
      className="welcome"
      aria-labelledby="welcome-title"
      aria-describedby="welcome-lede"
      onCancel={(event) => {
        event.preventDefault();
        dismiss("analyze");
      }}
    >
      <div className="welcome-body">
        <BrandMark className="welcome-mark" />
        <h1 id="welcome-title" className="welcome-title">
          Notes from any short video.
        </h1>
        <p id="welcome-lede" className="welcome-lede">
          Paste a link or add a file. VideoLens gives you a summary, notes and a transcript.
        </p>

        <ol className="welcome-steps">
          {STEPS.map((step, index) => (
            <li key={step.title} className="welcome-step">
              <span className="welcome-step-num" aria-hidden="true">
                {index + 1}
              </span>
              <span className="welcome-step-copy">
                <strong className="welcome-step-title">{step.title}</strong>
                <span className="welcome-step-text">{step.text}</span>
              </span>
            </li>
          ))}
        </ol>

        <div className="welcome-foot">
          <p className="welcome-note">
            You get runs every day, no account needed. Add your own Gemini key any time for more.
          </p>
          <button
            type="button"
            className="btn btn-primary btn-pill btn-block welcome-btn"
            onClick={() => dismiss("analyze")}
            autoFocus
          >
            Start analyzing
          </button>
          <button
            type="button"
            className="btn btn-secondary btn-pill btn-block welcome-btn"
            onClick={() => dismiss("api-key")}
          >
            Use my own Gemini key
          </button>
        </div>
      </div>
    </dialog>
  );
}
