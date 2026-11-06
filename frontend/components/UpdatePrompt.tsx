"use client";

import { useEffect, useRef, type KeyboardEvent, type MouseEvent } from "react";
import { Download } from "lucide-react";
import { useUpdateCheck } from "@/application/useUpdateCheck";
import { useFirstRunBusy } from "@/application/useFirstRun";

/* Hallmark · component: modal (update prompt) · genre: editorial · theme: custom (app/tokens.css)
 * states: hidden · waiting (splash / Welcome up) · open ·
 *         action default/hover/focus-visible/active · Later default/hover/focus-visible/active ·
 *         dismissed (Later, Escape, backdrop, Android back)
 * contrast: ink on surface 17.6:1 light / 15.4:1 dark; ink-2 on surface ≥ 11:1.
 *
 * Refinement 10 (owner: "it should be on screen, not at the top"). It was a
 * band at the top of .viewport (refinement 9); now a centred card over the
 * app on a dimmed backdrop. A native modal <dialog>, like the More sheet and
 * Welcome: the top layer, so it takes no layout space and cannot shift the
 * fixed nav / content band / footer frame; the page underneath is inert;
 * Android's hardware back finds it through `dialog[open]` and cancels it
 * (useHardwareBack), which lands in onCancel below like Escape does.
 *
 * Later, Escape, a backdrop tap and Android back all dismiss the same way:
 * the offered versionCode is remembered (useUpdateCheck → UpdateDismissalStore,
 * key `videolens-update-dismissed`), so this build is not offered again and a
 * newer one is.
 *
 * It waits while the cold-start splash or the first-run Welcome owns the
 * screen (useFirstRunBusy), and opens once they are gone.
 *
 * Native Android only (the check no-ops elsewhere). The link keeps
 * `target="_blank"`: in the Capacitor WebView that hands the release page to
 * the system browser (Chrome), which is what makes the APK download and the
 * install prompt work. Following it closes the prompt for this launch but
 * stores nothing: if the download is abandoned, it is offered again on the
 * next launch.
 *
 * Focus: into the action on open, Tab held between the two controls, and on
 * any close back to whatever had it before (restoreFocus) — never <body>. */

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])';

function isShown(element: Element): boolean {
  return element.getClientRects().length > 0;
}

/* Where focus goes when the prompt closes (device QA, refinement 10: the old
   banner dropped it on <body>). The element that had it before the prompt
   opened, if it is still on screen; otherwise the visible view's heading
   (made programmatically focusable, never tabbable); otherwise the first
   focusable control in that view; otherwise the first focusable control on
   the page. Never <body>. */
function restoreFocus(previous: HTMLElement | null): void {
  if (previous && previous.isConnected && isShown(previous)) {
    previous.focus({ preventScroll: true });
    if (document.activeElement === previous) return;
  }
  const main = Array.from(document.querySelectorAll("main")).find(isShown) ?? null;
  const heading = main?.querySelector<HTMLElement>("h1, h2") ?? null;
  if (heading && isShown(heading)) {
    if (!heading.hasAttribute("tabindex")) heading.setAttribute("tabindex", "-1");
    heading.focus({ preventScroll: true });
    if (document.activeElement === heading) return;
  }
  const scope: ParentNode = main ?? document;
  const first = Array.from(scope.querySelectorAll<HTMLElement>(FOCUSABLE)).find(isShown);
  first?.focus({ preventScroll: true });
}

export default function UpdatePrompt() {
  const { update, dismiss, close } = useUpdateCheck();
  const busy = useFirstRunBusy();
  const ref = useRef<HTMLDialogElement>(null);
  const actionRef = useRef<HTMLAnchorElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);

  const show = update !== null && !busy;

  useEffect(() => {
    const dialog = ref.current;
    if (!show || !dialog || dialog.open) return;
    const active = document.activeElement;
    returnFocus.current = active instanceof HTMLElement && active !== document.body ? active : null;
    dialog.showModal();
    actionRef.current?.focus();
    return () => {
      /* Closed (Later, Escape, backdrop, back, or the action): hand focus
         back. After the dialog has left the DOM, so the focus is not undone
         by the dialog's own close. */
      const previous = returnFocus.current;
      window.setTimeout(() => restoreFocus(previous), 0);
    };
  }, [show]);

  if (!show || !update) return null;

  /* A click whose target is the <dialog> itself can only be on ::backdrop —
     the padding lives on the card inside it. */
  const onDialogClick = (event: MouseEvent<HTMLDialogElement>) => {
    if (event.target === event.currentTarget) dismiss();
  };

  /* The top layer already makes the page inert; this keeps Tab cycling
     between the two controls instead of stepping out to the browser UI. */
  const onKeyDown = (event: KeyboardEvent<HTMLDialogElement>) => {
    if (event.key !== "Tab") return;
    const focusable = Array.from(
      event.currentTarget.querySelectorAll<HTMLElement>("a[href], button:not([disabled])"),
    );
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return (
    <dialog
      ref={ref}
      className="update-prompt"
      aria-modal="true"
      aria-labelledby="update-prompt-title"
      aria-describedby="update-prompt-text"
      onCancel={(event) => {
        event.preventDefault();
        dismiss();
      }}
      onClick={onDialogClick}
      onKeyDown={onKeyDown}
    >
      <div className="update-prompt__card">
        <span className="update-prompt__mark" aria-hidden="true">
          <Download />
        </span>
        <h2 id="update-prompt-title" className="update-prompt__title">
          Update available.
        </h2>
        <p id="update-prompt-text" className="update-prompt__text">
          Version {update.versionName} is ready to install.
        </p>
        <div className="update-prompt__actions">
          <a
            ref={actionRef}
            href={update.releaseUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="btn btn-ink btn-pill update-prompt__btn"
            onClick={() => {
              /* Close for this launch only (nothing stored), and only after
                 the click has finished: an anchor removed from the document
                 during its own click cannot navigate. */
              window.setTimeout(close, 0);
            }}
          >
            Get the update
          </a>
          <button type="button" className="btn btn-secondary btn-pill update-prompt__btn" onClick={dismiss}>
            Later
          </button>
        </div>
      </div>
    </dialog>
  );
}
