"use client";

import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { Check, Copy } from "lucide-react";
import { useAccount } from "@/application/useAccount";
import { useApiKeys } from "@/application/useApiKeys";
import {
  CODE_MAX_LENGTH,
  signOut,
  useAuthUser,
  useEmailCodeSignIn,
} from "@/application/useAuthSession";
import AppBackLink from "@/components/AppBackLink";
import { formatDay } from "@/components/format";
import type { ApiKeySummary, Capability } from "@/domain/entities";

/* Hallmark · component: account panel · genre: editorial · theme: custom
 * (owner handoff, app/tokens.css; no board drawn yet, so it reuses the API key
 * page's anatomy: serif header and lede, white `.key-card`s, pill buttons)
 * states: unavailable · loading · signed out (email, sending, code sent,
 *         verifying, field errors, resend countdown, run-in-progress guard) ·
 *         signed in (account loading, rejected, failed + retry) · API keys
 *         (loading, load error, empty, list, creating, one-time secret,
 *         copied, revoke confirm, revoking, revoked, action error)
 *
 * Auth phase 2 (docs/frontend/auth-sign-in.md). Sign-in is optional and the
 * page says so first. The emailed code is the only method this phase: Google
 * is phase 4 and has no button. Account deletion is phase 3 and is not
 * offered yet; a sentence says it is coming.
 *
 * Components never touch the provider: the session, `/api/me` and
 * `/api/keys` all come through the three application hooks. */

type AccountPanelProps = {
  /** The deployment's `auth` capability row, from HomeScreen's one
   *  `/api/capabilities` read. Anything but `ok` (including not arrived yet)
   *  means no sign-in form here; a leftover session can still sign out. */
  authCapability: Capability | null;
  /** True while a run is submitting, queued or processing on Analyze.
   *  Signing in or out changes who the server holds runs for, so the run on
   *  screen would stop answering (History keeps it: `recordGone`); the panel
   *  holds both actions until it settles. */
  runInProgress: boolean;
};

const RUN_GUARD =
  "A run is in progress on Analyze. Wait until it finishes: signing in or out now would stop this screen following it until you switch back.";

export default function AccountPanel({ authCapability, runInProgress }: AccountPanelProps) {
  const auth = useAuthUser();
  /* The same gate as the tab in HomeScreen: a provider in this build *and*
     the server's word that it verifies tokens. Still loading or failed
     counts as no, so nobody signs in to a server that would refuse the
     token (the API client would not send it anyway). */
  const available = auth.enabled && authCapability?.state === "ok";

  return (
    <div className="key-page acct-page">
      <AppBackLink />
      <header className="view-head">
        <h1 className="view-title">Account</h1>
        <p className="view-lede">
          Optional. VideoLens works the same without one. Signing in lets you make API keys so a
          script or an agent can run analyses as you. Your History stays in this browser either way.
        </p>
      </header>

      {!available ? (
        <>
          <Unavailable />
          {/* A session left over from a server that did take sign-in (or one
              whose report has not arrived): Sign out stays reachable here,
              at /app?view=account, even with the tab hidden. */}
          {auth.ready && auth.user && (
            <IdentityCard email={auth.user.email} runInProgress={runInProgress} />
          )}
        </>
      ) : !auth.ready ? (
        <p role="status" className="pending-note acct-gap">
          Loading…
        </p>
      ) : auth.user ? (
        <SignedIn userId={auth.user.id} email={auth.user.email} runInProgress={runInProgress} />
      ) : (
        <SignInCard runInProgress={runInProgress} />
      )}
    </div>
  );
}

function Unavailable() {
  return (
    <section className="key-card" aria-labelledby="acct-off-title">
      <h2 id="acct-off-title" className="acct-card-title">
        Sign-in is not available on this server
      </h2>
      <p className="key-help">
        Everything else works without an account: analyze, History, and your own Gemini key under API
        key.
      </p>
    </section>
  );
}

/* ---------------------------------------------------------------- signed out */

function SignInCard({ runInProgress }: { runInProgress: boolean }) {
  const flow = useEmailCodeSignIn();
  const emailId = useId();
  const emailHelpId = useId();
  const emailErrorId = useId();
  const codeId = useId();
  const codeHelpId = useId();
  const codeErrorId = useId();
  const emailRef = useRef<HTMLInputElement>(null);
  const codeRef = useRef<HTMLInputElement>(null);

  const codeStep = flow.phase === "code-sent" || flow.phase === "verifying" || (flow.phase === "sending" && flow.sentTo);
  const emailError = flow.error?.field === "email" ? flow.error.message : null;
  const codeError = flow.error?.field === "code" ? flow.error.message : null;

  /* Focus follows the step: the code field when a code goes out, the field
     with the problem when one is refused. */
  useEffect(() => {
    if (flow.phase === "code-sent" && !codeError) codeRef.current?.focus();
  }, [flow.phase, flow.sentTo, codeError]);
  useEffect(() => {
    if (emailError) emailRef.current?.focus();
  }, [emailError]);
  useEffect(() => {
    if (codeError) codeRef.current?.focus();
  }, [codeError]);

  const sendCode = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void flow.send();
  };

  const verify = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (runInProgress) return;
    void flow.verify();
  };

  if (!codeStep) {
    const sending = flow.phase === "sending";
    return (
      <form className="key-card" onSubmit={sendCode} noValidate aria-label="Sign in">
        <label htmlFor={emailId} className="key-label">
          Email
        </label>
        <input
          ref={emailRef}
          id={emailId}
          type="email"
          inputMode="email"
          autoComplete="email"
          autoCapitalize="off"
          autoCorrect="off"
          spellCheck={false}
          className="field acct-field"
          value={flow.email}
          onChange={(event) => flow.setEmail(event.target.value)}
          placeholder="you@example.com"
          aria-invalid={emailError ? true : undefined}
          aria-describedby={emailError ? `${emailErrorId} ${emailHelpId}` : emailHelpId}
        />
        {emailError && (
          <p id={emailErrorId} role="alert" className="error-note key-error">
            {emailError}
          </p>
        )}
        <p id={emailHelpId} className="key-help">
          We email you a sign-in code. There is no password. The first code also creates your
          account.
        </p>
        <div className="key-actions">
          <button
            type="submit"
            className="btn btn-primary btn-pill"
            aria-disabled={sending || undefined}
          >
            {sending ? "Sending…" : "Send code"}
          </button>
        </div>
      </form>
    );
  }

  const verifying = flow.phase === "verifying";
  const resending = flow.phase === "sending";
  return (
    <form className="key-card" onSubmit={verify} noValidate aria-label="Enter your code">
      <label htmlFor={codeId} className="key-label">
        Code from the email
      </label>
      <p id={codeHelpId} className="key-help acct-help-top">
        We sent a code to <strong className="acct-strong">{flow.sentTo}</strong>. It expires in 10
        minutes.
      </p>
      <input
        ref={codeRef}
        id={codeId}
        type="text"
        inputMode="numeric"
        autoComplete="one-time-code"
        pattern="[0-9]*"
        maxLength={CODE_MAX_LENGTH + 4}
        spellCheck={false}
        className="field acct-field acct-code"
        value={flow.code}
        onChange={(event) => flow.setCode(event.target.value)}
        placeholder="12345678"
        aria-invalid={codeError ? true : undefined}
        aria-describedby={codeError ? `${codeErrorId} ${codeHelpId}` : codeHelpId}
      />
      {codeError && (
        <p id={codeErrorId} role="alert" className="error-note key-error">
          {codeError}
        </p>
      )}
      {runInProgress && <p className="pending-note acct-guard">{RUN_GUARD}</p>}
      <div className="key-actions">
        <button
          type="submit"
          className="btn btn-primary btn-pill"
          aria-disabled={verifying || resending || runInProgress || undefined}
        >
          {verifying ? "Verifying…" : "Verify"}
        </button>
        <p role="status" className="key-status-slot">
          {resending && <span className="key-status">Sending a new code…</span>}
        </p>
      </div>
      <div className="acct-links">
        {flow.resendIn > 0 ? (
          <span className="acct-quiet">Send a new code in {flow.resendIn}s</span>
        ) : (
          <button type="button" className="acct-link" onClick={flow.resend} aria-disabled={resending || undefined}>
            Send a new code
          </button>
        )}
        <button type="button" className="acct-link" onClick={flow.changeEmail}>
          Use a different email
        </button>
      </div>
    </form>
  );
}

/* ----------------------------------------------------------------- signed in */

function SignedIn({
  userId,
  email,
  runInProgress,
}: {
  userId: string;
  email: string | null;
  runInProgress: boolean;
}) {
  const { account, problem, loading, reload } = useAccount(userId);
  const identity = <IdentityCard email={account?.email ?? email} runInProgress={runInProgress} />;

  if (problem?.kind === "unavailable") {
    return (
      <>
        <Unavailable />
        {identity}
      </>
    );
  }

  return (
    <>
      {identity}

      {loading && (
        <p role="status" className="pending-note acct-gap">
          Loading your account…
        </p>
      )}

      {problem?.kind === "rejected" && (
        <div role="alert" className="error-inline acct-gap">
          <p>This server did not accept your sign-in. Sign out, then sign in again.</p>
        </div>
      )}

      {problem?.kind === "failed" && (
        <div role="alert" className="error-inline acct-gap">
          <p>{problem.message}</p>
          <button type="button" className="btn btn-secondary" onClick={reload}>
            Try again
          </button>
        </div>
      )}

      {account && (
        <ApiKeysSection enabled={account.accounts_enabled && account.workspace !== null} />
      )}

      {account && (
        <p className="pending-note acct-gap">
          Deleting your account from the app is coming soon. Until then, ask us and we will delete it.
        </p>
      )}
    </>
  );
}

function IdentityCard({ email, runInProgress }: { email: string | null; runInProgress: boolean }) {
  const [signingOut, setSigningOut] = useState(false);

  const handleSignOut = () => {
    if (signingOut || runInProgress) return;
    setSigningOut(true);
    void signOut().finally(() => setSigningOut(false));
  };

  return (
    <section className="key-card" aria-labelledby="acct-id-title">
      <h2 id="acct-id-title" className="key-label">
        Signed in as
      </h2>
      <p className="acct-email">{email ?? "your account"}</p>
      <p className="key-help">Signing out applies to this device only. Your History stays here.</p>
      {runInProgress && <p className="pending-note acct-guard">{RUN_GUARD}</p>}
      <div className="key-actions">
        <button
          type="button"
          className="btn btn-secondary btn-pill key-remove"
          onClick={handleSignOut}
          aria-disabled={signingOut || runInProgress || undefined}
        >
          {signingOut ? "Signing out…" : "Sign out"}
        </button>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ API keys */

function ApiKeysSection({ enabled }: { enabled: boolean }) {
  const { keys, loadError, actionError, busy, create, revoke, reload, justCreated, dismissSecret } =
    useApiKeys(enabled);
  const [name, setName] = useState("");
  const [confirming, setConfirming] = useState<string | null>(null);
  const nameId = useId();
  const helpId = useId();

  if (!enabled) {
    return (
      <section className="key-card" aria-labelledby="acct-keys-title">
        <h2 id="acct-keys-title" className="acct-card-title">
          API keys
        </h2>
        <p className="key-help">This server does not keep accounts, so it cannot issue API keys.</p>
      </section>
    );
  }

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void create(name).then((made) => {
      if (made) setName("");
    });
  };

  const active = keys?.filter((key) => key.active && !key.revoked_at) ?? [];
  const revoked = keys?.filter((key) => !key.active || key.revoked_at) ?? [];

  return (
    <section className="key-card" aria-labelledby="acct-keys-title">
      <h2 id="acct-keys-title" className="acct-card-title">
        API keys
      </h2>
      <p className="key-help acct-help-top">
        A key lets a script or an agent call the VideoLens API as you. Send it in an{" "}
        <code className="acct-inline-code">X-Api-Key</code> header. Keep it secret.
      </p>

      {justCreated && (
        <SecretReveal secret={justCreated.secret} name={justCreated.name} onDismiss={dismissSecret} />
      )}

      <form className="acct-create" onSubmit={submit} noValidate>
        <label htmlFor={nameId} className="key-label">
          New key name
        </label>
        <div className="key-row">
          <input
            id={nameId}
            className="field acct-field"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="What will use it, e.g. Claude Code"
            maxLength={80}
            autoComplete="off"
            spellCheck={false}
            aria-describedby={helpId}
          />
          <button type="submit" className="btn btn-primary btn-pill acct-create-btn" aria-disabled={busy !== null || undefined}>
            {busy === "create" ? "Creating…" : "Create key"}
          </button>
        </div>
        <p id={helpId} className="key-help">
          The name is only for you. Up to 10 active keys.
        </p>
      </form>

      {actionError && (
        <p role="alert" className="error-note acct-gap-sm">
          {actionError.message}
        </p>
      )}

      {loadError ? (
        <div role="alert" className="error-inline acct-gap-sm">
          <p>{loadError.message}</p>
          <button type="button" className="btn btn-secondary" onClick={reload}>
            Try again
          </button>
        </div>
      ) : keys === null ? (
        <p role="status" className="pending-note acct-gap-sm">
          Loading keys…
        </p>
      ) : keys.length === 0 ? (
        <p className="pending-note acct-gap-sm">No keys yet.</p>
      ) : (
        <ul className="acct-key-list" aria-label="Your API keys">
          {[...active, ...revoked].map((apiKey) => (
            <KeyRow
              key={apiKey.key_id}
              apiKey={apiKey}
              confirming={confirming === apiKey.key_id}
              revoking={busy === apiKey.key_id}
              onAsk={() => setConfirming(apiKey.key_id)}
              onCancel={() => setConfirming(null)}
              onConfirm={() =>
                void revoke(apiKey.key_id).then((done) => {
                  if (done) setConfirming(null);
                })
              }
            />
          ))}
        </ul>
      )}
    </section>
  );
}

function SecretReveal({ secret, name, onDismiss }: { secret: string; name: string; onDismiss: () => void }) {
  const [copied, setCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);
  const valueRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!copied) return;
    const handle = window.setTimeout(() => setCopied(false), 1600);
    return () => window.clearTimeout(handle);
  }, [copied]);

  const copy = () => {
    const done = () => {
      setCopyFailed(false);
      setCopied(true);
    };
    const fail = () => {
      /* No clipboard here (an insecure origin, a refusing WebView): select
         the text so a long-press or Ctrl+C still gets it. */
      setCopyFailed(true);
      const node = valueRef.current;
      const selection = window.getSelection();
      if (node && selection) {
        const range = document.createRange();
        range.selectNodeContents(node);
        selection.removeAllRanges();
        selection.addRange(range);
      }
    };
    if (navigator.clipboard?.writeText) navigator.clipboard.writeText(secret).then(done, fail);
    else fail();
  };

  return (
    <div className="acct-secret" role="status">
      <p className="acct-secret-lede">
        <strong className="acct-strong">{name}</strong> is ready. Copy it now: this is the only time it is
        shown. The server keeps only a fingerprint of it.
      </p>
      <code ref={valueRef} className="acct-secret-value">
        {secret}
      </code>
      {copyFailed && <p className="pending-note">Copying is blocked here. The key is selected; copy it by hand.</p>}
      <div className="key-actions acct-secret-actions">
        <button
          type="button"
          className="btn btn-secondary btn-pill"
          onClick={copy}
          data-state={copied ? "copied" : undefined}
        >
          {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
          {copied ? "Copied" : "Copy key"}
        </button>
        <button type="button" className="btn btn-secondary btn-pill key-remove" onClick={onDismiss}>
          Done
        </button>
      </div>
    </div>
  );
}

function KeyRow({
  apiKey,
  confirming,
  revoking,
  onAsk,
  onCancel,
  onConfirm,
}: {
  apiKey: ApiKeySummary;
  confirming: boolean;
  revoking: boolean;
  onAsk: () => void;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const revoked = !apiKey.active || apiKey.revoked_at !== null;
  return (
    <li className="acct-key" data-revoked={revoked ? "true" : undefined}>
      <div className="acct-key-text">
        <span className="acct-key-name">{apiKey.name}</span>
        <span className="acct-key-meta">
          <code className="acct-inline-code">{apiKey.prefix}…</code>
          <span> · Created {formatDay(apiKey.created_at)}</span>
          {apiKey.last_used_at && <span> · Last used {formatDay(apiKey.last_used_at)}</span>}
        </span>
      </div>
      {revoked ? (
        <span className="chip acct-chip">Revoked</span>
      ) : confirming ? (
        <div className="acct-confirm" role="group" aria-label={`Revoke ${apiKey.name}?`}>
          <span className="acct-confirm-q">Revoke? Anything using it stops working.</span>
          <button type="button" className="btn btn-pill acct-danger" onClick={onConfirm} aria-disabled={revoking || undefined}>
            {revoking ? "Revoking…" : "Revoke"}
          </button>
          <button type="button" className="btn btn-secondary btn-pill key-remove" onClick={onCancel}>
            Keep
          </button>
        </div>
      ) : (
        <button type="button" className="btn btn-secondary btn-pill key-remove acct-revoke" onClick={onAsk}>
          Revoke
        </button>
      )}
    </li>
  );
}
