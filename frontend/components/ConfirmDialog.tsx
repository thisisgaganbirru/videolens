"use client";

import { useEffect, useRef, type KeyboardEvent, type MouseEvent, type ReactNode } from "react";

/* Hallmark · component: modal (destructive confirm) · genre: editorial · theme: custom (app/tokens.css)
 * states: closed · open · busy (confirm aria-disabled, label says so) · failed (inline line, retry) ·
 *         confirm default/hover/focus-visible/active · cancel default/hover/focus-visible/active ·
 *         dismissed (Cancel, Escape, backdrop, Android back)
 *
 * Saved history (2026-11-14). A native modal <dialog> on the update prompt's
 * card (`.update-prompt*`), so it sits in the top layer, takes no layout
 * space and cannot shift the fixed frame; Android's back cancels it through
 * `dialog[open]` (useHardwareBack) like Escape. Focus lands on Cancel, the
 * safe choice, and goes back to whatever opened it. The confirm is the one
 * solid-danger control on screen while it is open: red is for errors and for
 * removing something for good. Nothing closes it while the delete is on the
 * wire, so the answer is never lost behind a dismissed card. */

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  children: ReactNode;
  confirmLabel: string;
  busyLabel: string;
  busy: boolean;
  /** Shown under the text when the last attempt failed. */
  error: string | null;
  onConfirm: () => void;
  onCancel: () => void;
}

export default function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel,
  busyLabel,
  busy,
  error,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!open || !dialog || dialog.open) return;
    const active = document.activeElement;
    returnFocus.current = active instanceof HTMLElement && active !== document.body ? active : null;
    dialog.showModal();
    cancelRef.current?.focus();
    return () => {
      if (dialog.open) dialog.close();
      const previous = returnFocus.current;
      window.setTimeout(() => {
        if (previous?.isConnected && previous.getClientRects().length > 0) {
          previous.focus({ preventScroll: true });
          return;
        }
        const heading = Array.from(document.querySelectorAll<HTMLElement>("main h1")).find(
          (el) => el.getClientRects().length > 0
        );
        if (heading) {
          if (!heading.hasAttribute("tabindex")) heading.setAttribute("tabindex", "-1");
          heading.focus({ preventScroll: true });
        }
      }, 0);
    };
  }, [open]);

  if (!open) return null;

  const dismiss = () => {
    if (!busy) onCancel();
  };

  const onDialogClick = (event: MouseEvent<HTMLDialogElement>) => {
    if (event.target === event.currentTarget) dismiss();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDialogElement>) => {
    if (event.key !== "Tab") return;
    const focusable = Array.from(event.currentTarget.querySelectorAll<HTMLElement>("button"));
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
      className="update-prompt confirm-dialog"
      aria-labelledby="confirm-dialog-title"
      onCancel={(event) => {
        event.preventDefault();
        dismiss();
      }}
      onClick={onDialogClick}
      onKeyDown={onKeyDown}
    >
      <div className="update-prompt__card">
        <h2 id="confirm-dialog-title" className="update-prompt__title">
          {title}
        </h2>
        <div className="update-prompt__text">{children}</div>
        {error ? (
          <p role="alert" className="error-inline confirm-dialog__error">
            {error}
          </p>
        ) : null}
        <div className="update-prompt__actions">
          <button
            type="button"
            className="btn btn-pill acct-danger update-prompt__btn"
            aria-disabled={busy || undefined}
            onClick={() => {
              if (!busy) onConfirm();
            }}
          >
            {busy ? busyLabel : confirmLabel}
          </button>
          <button
            ref={cancelRef}
            type="button"
            className="btn btn-secondary update-prompt__btn"
            aria-disabled={busy || undefined}
            onClick={dismiss}
          >
            Cancel
          </button>
        </div>
      </div>
    </dialog>
  );
}
