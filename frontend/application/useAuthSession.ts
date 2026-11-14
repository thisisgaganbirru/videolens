"use client";

import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import type { AuthUser } from "@/domain/entities";
import { AuthFlowError, type AuthFailureReason } from "@/domain/errors";
import { authSession } from "@/infrastructure/container";

/* The signed-in state as React sees it, and the emailed-code sign-in flow
   (auth phase 2). See docs/frontend/auth-sign-in.md.

   Two hooks, because two different places need two different things:
   `HomeScreen` only needs to know *who* is signed in (to re-import History
   and to keep the Account tab honest), while the Account panel also owns the
   form state of a sign-in in progress. One provider subscription each; the
   session object itself is the single source of truth. */

/**
 * Who is signed in. `ready` flips once the provider has loaded (or refused
 * to), so a panel can tell "nobody is signed in" from "not known yet", which
 * render differently. On a deployment with no provider `ready` is true from
 * the first render and `user` is always null.
 *
 * Read after hydration, never during render: the stored session lives in
 * localStorage, and the prerendered HTML must match the first client render.
 */
export function useAuthUser() {
  const [state, setState] = useState<{ ready: boolean; user: AuthUser | null }>({
    ready: !authSession.enabled,
    user: null,
  });

  useEffect(() => {
    if (!authSession.enabled) return;
    let cancelled = false;
    /* Only a change of person re-renders: the provider also notifies on
       every hourly token refresh, which changes nothing anyone draws. */
    const sync = () => {
      if (cancelled) return;
      const next = authSession.user();
      setState((current) =>
        current.ready && current.user?.id === next?.id && current.user?.email === next?.email
          ? current
          : { ready: true, user: next }
      );
    };
    const unsubscribe = authSession.subscribe(sync);
    authSession
      .load()
      .catch(() => {
        /* A provider that will not load leaves the app anonymous. The
           Account panel says so when someone tries to sign in. */
      })
      .finally(sync);
    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, []);

  return { enabled: authSession.enabled, ready: state.ready, user: state.user };
}

const noSession = () => false;
const storedSession = () => authSession.hasSession();
const subscribeSession = (onChange: () => void) => authSession.subscribe(onChange);

/**
 * A session is stored on this device, before the provider has loaded and
 * `useAuthUser().ready` turns true. Only a hint for holding layout (the
 * Gemini key page's sign-in line), never for who is signed in: the stored
 * session may yet turn out to be expired. False during prerender and
 * hydration (localStorage is not read during render there); the client
 * value follows right after.
 */
export function useStoredSessionHint(): boolean {
  return useSyncExternalStore(subscribeSession, storedSession, noSession);
}

/** Where the emailed-code flow is. "Email entered" is `idle` with a
 *  non-empty `email`; an error keeps the phase it happened in. */
export type SignInPhase = "idle" | "sending" | "code-sent" | "verifying";

export type SignInError = { field: "email" | "code"; message: string };

/** Supabase refuses a second code for the same address inside 60 s. */
export const RESEND_AFTER_SECONDS = 60;

/** The code length the project sends is a dashboard setting (6 by Supabase's
 *  old default, 8 by the current one, which `videolens-dev` uses); accept the
 *  whole range so a settings change never locks anyone out. */
export const CODE_MIN_LENGTH = 6;
export const CODE_MAX_LENGTH = 8;

const EMAIL_SHAPE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const REASON_MESSAGE: Record<AuthFailureReason, string> = {
  invalid_email: "Enter a valid email address.",
  invalid_code: "That code is wrong or has expired. Check the latest email, or send a new code.",
  rate_limited: "Too many attempts. Wait a minute, then try again.",
  unreachable: "Can't reach the sign-in service. Check your connection and try again.",
  unavailable: "Sign-in is not available on this server.",
  unknown: "Sign-in did not work. Try again.",
};

function messageFor(err: unknown): string {
  return REASON_MESSAGE[err instanceof AuthFlowError ? err.reason : "unknown"];
}

/** Keeps digits only, so a pasted "1234 5678" or "Code: 12345678" works. */
export function cleanCode(raw: string): string {
  return raw.replace(/\D/g, "").slice(0, CODE_MAX_LENGTH);
}

/**
 * The emailed one-time code sign-in. No redirect and no deep link, so it is
 * the same in a browser tab and inside the installed app's WebView.
 *
 * Every action is guarded rather than disabled: a focused control that turns
 * `disabled` is blurred to <body>, and a keyboard user loses their place.
 */
export function useEmailCodeSignIn() {
  const [phase, setPhase] = useState<SignInPhase>("idle");
  const [email, setEmailValue] = useState("");
  /** The address the code was actually sent to; `email` may be edited after. */
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [code, setCodeValue] = useState("");
  const [error, setError] = useState<SignInError | null>(null);
  const [sentAt, setSentAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());

  /* The resend countdown ticks only while there is something to count. */
  useEffect(() => {
    if (sentAt === null) return;
    const handle = window.setInterval(() => {
      const t = Date.now();
      setNow(t);
      if (t - sentAt >= RESEND_AFTER_SECONDS * 1000) window.clearInterval(handle);
    }, 1000);
    return () => window.clearInterval(handle);
  }, [sentAt]);

  const resendIn = sentAt === null ? 0 : Math.max(0, Math.ceil((sentAt + RESEND_AFTER_SECONDS * 1000 - now) / 1000));

  const setEmail = useCallback((next: string) => {
    setEmailValue(next);
    setError((current) => (current?.field === "email" ? null : current));
  }, []);

  const setCode = useCallback((next: string) => {
    setCodeValue(cleanCode(next));
    setError((current) => (current?.field === "code" ? null : current));
  }, []);

  const send = useCallback(
    async (target?: string) => {
      if (phase === "sending" || phase === "verifying") return;
      const address = (target ?? email).trim();
      if (!EMAIL_SHAPE.test(address)) {
        setError({ field: "email", message: REASON_MESSAGE.invalid_email });
        return;
      }
      const resending = phase === "code-sent";
      setPhase("sending");
      setError(null);
      try {
        await authSession.requestEmailCode(address);
        const t = Date.now();
        setSentTo(address);
        setSentAt(t);
        setNow(t);
        setCodeValue("");
        setPhase("code-sent");
      } catch (err) {
        setPhase(resending ? "code-sent" : "idle");
        setError({ field: resending ? "code" : "email", message: messageFor(err) });
      }
    },
    [email, phase]
  );

  const resend = useCallback(() => {
    if (resendIn > 0 || !sentTo) return;
    void send(sentTo);
  }, [resendIn, send, sentTo]);

  const verify = useCallback(async () => {
    if (phase !== "code-sent" || !sentTo) return;
    if (code.length < CODE_MIN_LENGTH) {
      setError({ field: "code", message: "Enter the code from the email. It is 6 to 8 digits." });
      return;
    }
    setPhase("verifying");
    setError(null);
    try {
      await authSession.verifyEmailCode(sentTo, code);
      /* Signed in: the session notifies `useAuthUser`, which swaps the panel
         to the signed-in view. Reset so a later sign-out starts clean. */
      setPhase("idle");
      setSentTo(null);
      setSentAt(null);
      setCodeValue("");
    } catch (err) {
      setPhase("code-sent");
      setError({ field: "code", message: messageFor(err) });
    }
  }, [code, phase, sentTo]);

  /** Back to the email step, keeping what was typed. */
  const changeEmail = useCallback(() => {
    if (phase === "sending" || phase === "verifying") return;
    setPhase("idle");
    setSentTo(null);
    setSentAt(null);
    setCodeValue("");
    setError(null);
  }, [phase]);

  return { phase, email, setEmail, sentTo, code, setCode, error, send, resend, resendIn, verify, changeEmail };
}

/** Signs out on this device. History stays: it is this browser's, not the
 *  account's. */
export function signOut(): Promise<void> {
  return authSession.signOut();
}

/** Where "Sign out everywhere" is. `failed` keeps the person signed in. */
export type SignOutEverywherePhase = "idle" | "working" | "failed";

/**
 * Ends every session of the signed-in person, this device last. On success
 * the session listeners fire and the panel falls back to the signed-out view
 * as after `signOut()`. On failure nothing changes here and `error` says so.
 *
 * Other devices are signed out at their next token refresh: the API checks
 * tokens by signature only, so an access token already issued keeps working
 * until it expires (up to an hour). VideoLens API keys are not revoked.
 */
export function useSignOutEverywhere() {
  const [phase, setPhase] = useState<SignOutEverywherePhase>("idle");
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async () => {
    if (phase === "working") return;
    setPhase("working");
    setError(null);
    try {
      await authSession.signOutEverywhere();
      setPhase("idle");
    } catch (err) {
      const reason = err instanceof AuthFlowError ? err.reason : "unknown";
      setError(
        reason === "unreachable"
          ? "Can't reach the sign-in service, so nothing changed. You are still signed in. Check your connection and try again."
          : reason === "rate_limited"
            ? "Too many attempts. Wait a minute, then try again. You are still signed in."
            : "Signing out everywhere did not work. You are still signed in. Try again."
      );
      setPhase("failed");
    }
  }, [phase]);

  return { phase, error, run };
}
