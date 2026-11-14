"use client";

import { useCallback, useEffect, useId, useRef, useState, type FormEvent } from "react";
import Link from "next/link";
import { Check, ChevronDown, ChevronRight, Copy } from "lucide-react";
import { useAccount, useAccountDeletion } from "@/application/useAccount";
import { useApiKeys } from "@/application/useApiKeys";
import {
  CODE_MAX_LENGTH,
  signOut,
  useAuthUser,
  useEmailCodeSignIn,
  useSignOutEverywhere,
} from "@/application/useAuthSession";
import AppBackLink from "@/components/AppBackLink";
import { isPlainLeftClick } from "@/components/navClick";
import { goToMainTab, mainTabHref, type MainTab } from "@/application/useMainTab";
import { formatDay, formatLongDay, formatPrice } from "@/components/format";
import type { ApiKeySummary, BillingDetails, Capability } from "@/domain/entities";
import type { FreeRunsBanner } from "@/application/useFreeRuns";
import { useBillingActions, type BillingAction, type CheckoutReturn } from "@/application/useBilling";
import { ACCOUNT_FREE_RUNS_PER_MONTH } from "@/application/accountAllowance";

/* Hallmark · component: account panel · genre: editorial · theme: custom
 * (owner handoff, app/tokens.css) · layout: option A, grouped list (owner's
 * pick, 2026-11-09): identity card, then small uppercase group labels over
 * white grouped cards of hairline rows, then the quiet account-ending
 * controls last
 * states: unavailable · loading · signed out (email, sending, code sent,
 *         verifying, field errors, resend countdown, run-in-progress guard) ·
 *         signed in (account loading, rejected, failed + retry) · API keys
 *         (collapsed, count once known, unseen-secret flag, loading, load
 *         error, empty, list, creating, one-time secret, copied, revoke
 *         confirm, revoking, revoked, action error) · sign out everywhere
 *         (idle, run guard, working, failed and still signed in) · delete
 *         account (quiet link, confirming with typed email, run guard,
 *         deleting, failed: rejected / unavailable / unreachable / generic,
 *         not offered when the server keeps no accounts, deleted card) ·
 *         plan (absent when billing is off · free: pitch, monthly/yearly
 *         buttons, a null price hides its button · paid: interval, renews /
 *         ends, payment failed, runs used, extra-run price, Manage billing ·
 *         opening, handed off to the browser, action error) · checkout
 *         return notice (confirming, paid, cancelled, unconfirmed,
 *         signed-out variant)
 *
 * Auth phases 2 and 3 (docs/frontend/auth-sign-in.md). Sign-in is optional
 * and the page says so first. The emailed code is the only method: Google
 * is phase 4 and has no button. Deletion is the very last item, a muted link
 * that opens the form, and is confirmed by typing the account's email.
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
  /** The free-run allowance, from HomeScreen's one `useFreeRuns` read: the
   *  account's for the month when the server counts it (`scope: "account"`),
   *  else this device's for the day. Null when unknown, unlimited, or beside
   *  the point (a Gemini key is saved): the identity line then says nothing
   *  about free runs. */
  freeRuns: FreeRunsBanner | null;
  /** The signed-in account's plan, from HomeScreen's one `useBilling` read.
   *  Null when billing is off, the server's `billing` capability is not
   *  `ok`, nobody is signed in, or the read failed: no Plan group at all, so
   *  the panel looks exactly as it did before billing existed. */
  billing: BillingDetails | null;
  /** Set when this load came back from Stripe Checkout
   *  (`?billing=success|cancel`, already stripped from the address). */
  checkoutReturn: CheckoutReturn | null;
  /** The paid tier's video length in minutes, when the server reports one;
   *  null leaves the length out of the pitch rather than guess it. */
  paidMinutes: number | null;
  /** The video length signing in unlocks on the user's own key, in minutes
   *  (`useMediaLimits().upgradeMinutes`); null (limits not read, or no larger
   *  tier) leaves the length out of the lede rather than promise it. Only the
   *  signed-out lede reads it. */
  signInMinutes: number | null;
};

/** The paid plan's monthly allowance, as sold (owner, 2026-11-13). The live
 *  number comes from `billing.runs.limit` once someone is on the plan. */
const PAID_RUNS_PER_MONTH = 100;

const RUN_GUARD =
  "A run is in progress on Analyze. Wait until it finishes: signing in or out now would stop this screen following it until you switch back.";

export default function AccountPanel({
  authCapability,
  runInProgress,
  freeRuns,
  billing,
  checkoutReturn,
  paidMinutes,
  signInMinutes,
}: AccountPanelProps) {
  const auth = useAuthUser();
  /* Held here, above the signed-in view: deleting signs out, which unmounts
     that view, and the confirmation has to outlive it. */
  /* "signing-out" until the stored session is cleared: going back to the
     sign-in view earlier would mount the signed-in view on the old token. */
  const [deleted, setDeleted] = useState<false | "signing-out" | "done">(false);
  const markDeleted = useCallback((signedOut: Promise<void>) => {
    setDeleted("signing-out");
    void signedOut.then(() => setDeleted((d) => (d ? "done" : d)));
  }, []);
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
          {auth.user
            ? "Your sign-in, connected tools, and data on this device."
            : signInMinutes
              ? `Sign in for ${ACCOUNT_FREE_RUNS_PER_MONTH} free runs a month, videos up to ${signInMinutes} minutes with your own key, and API keys for your scripts. An account is optional.`
              : `Sign in for ${ACCOUNT_FREE_RUNS_PER_MONTH} free runs a month and API keys for your scripts. An account is optional.`}
        </p>
      </header>

      {/* Always mounted so the change is announced; empty, it takes no space. */}
      <div role="status" className="acct-plan-notice-slot">
        {checkoutReturn && !deleted && (
          <p className="key-card acct-plan-notice" data-tone={checkoutReturn === "cancelled" ? "quiet" : undefined}>
            {checkoutNotice(checkoutReturn, auth.ready && auth.user !== null)}
          </p>
        )}
      </div>

      {deleted ? (
        <DeletedCard signingOut={deleted === "signing-out"} onBack={() => setDeleted(false)} />
      ) : !available ? (
        <>
          <Unavailable />
          {/* A session left over from a server that did take sign-in (or one
              whose report has not arrived): Sign out stays reachable here,
              at /app?view=account, even with the tab hidden. */}
          {auth.ready && auth.user && (
            <IdentityCard email={auth.user.email} runInProgress={runInProgress} freeRuns={freeRuns} />
          )}
        </>
      ) : !auth.ready ? (
        <p role="status" className="pending-note acct-gap">
          Loading…
        </p>
      ) : auth.user ? (
        <SignedIn
          userId={auth.user.id}
          email={auth.user.email}
          runInProgress={runInProgress}
          freeRuns={freeRuns}
          billing={billing}
          paidMinutes={paidMinutes}
          onDeleted={markDeleted}
        />
      ) : (
        <SignInCard runInProgress={runInProgress} />
      )}
      {(deleted || !available || !auth.user) && <AccountResources />}
    </div>
  );
}

function checkoutNotice(notice: CheckoutReturn, signedIn: boolean): string {
  if (notice === "cancelled") return "Checkout cancelled. Nothing was charged.";
  if (!signedIn) return "Checkout finished. Sign in with the email you paid with to see your plan.";
  if (notice === "paid") return "You’re on the paid plan.";
  if (notice === "confirming") return "Confirming payment…";
  return "We have not seen your payment yet. If you completed checkout, it will show here shortly.";
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
      <form className="key-card acct-sign-in" onSubmit={sendCode} noValidate aria-label="Sign in or create an account">
        <h2 className="acct-card-title">Sign in or create an account</h2>
        <p className="key-help acct-form-intro">We’ll send you a code. No password needed.</p>
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
          readOnly={sending}
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
          New here? Verifying your first code sets it up.
        </p>
        <div className="key-actions">
          <button
            type="submit"
            className="btn btn-primary btn-pill"
            aria-disabled={sending || undefined}
          >
            {sending ? "Sending…" : "Send code"}
          </button>
          <p role="status" className="key-status-slot">
            {sending && <span className="key-status">Sending your code…</span>}
          </p>
        </div>
      </form>
    );
  }

  const verifying = flow.phase === "verifying";
  const resending = flow.phase === "sending";
  return (
    <form className="key-card acct-sign-in" onSubmit={verify} noValidate aria-label="Enter your code">
      <h2 className="acct-card-title">Check your email</h2>
      <p id={codeHelpId} className="key-help acct-form-intro">
        Enter the code sent to <strong className="acct-strong">{flow.sentTo}</strong>.
        It expires in 10 minutes.
      </p>
      <label htmlFor={codeId} className="key-label">
        Code from the email
      </label>
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
        readOnly={verifying || resending}
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
          {verifying && <span className="key-status">Checking your code…</span>}
        </p>
      </div>
      <div className="acct-links">
        {flow.resendIn > 0 ? (
          <span className="acct-quiet">Send a new code in {flow.resendIn}s</span>
        ) : (
          <button type="button" className="acct-link" onClick={flow.resend} aria-disabled={resending || verifying || undefined}>
            Send a new code
          </button>
        )}
        <button type="button" className="acct-link" onClick={flow.changeEmail} aria-disabled={resending || verifying || undefined}>
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
  freeRuns,
  billing,
  paidMinutes,
  onDeleted,
}: {
  userId: string;
  email: string | null;
  runInProgress: boolean;
  freeRuns: FreeRunsBanner | null;
  billing: BillingDetails | null;
  paidMinutes: number | null;
  onDeleted: (signedOut: Promise<void>) => void;
}) {
  const { account, problem, loading, reload } = useAccount(userId);
  const identity = (
    <IdentityCard email={account?.email ?? email} runInProgress={runInProgress} freeRuns={freeRuns} />
  );

  if (problem?.kind === "unavailable") {
    return (
      <>
        <Unavailable />
        {identity}
        <AccountResources />
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

      {billing && <PlanGroup billing={billing} paidMinutes={paidMinutes} />}

      {account && (
        <section className="acct-group" aria-labelledby="acct-grp-account">
          <h2 id="acct-grp-account" className="history-group-label acct-group-label">
            Your account
          </h2>
          <ApiKeyManager key={userId} enabled={account.accounts_enabled && account.workspace !== null} />
        </section>
      )}

      <AccountResources signedIn />

      {/* Last on the page, on purpose: the two controls that end something. */}
      <section className="acct-end" aria-labelledby="acct-end-title">
        <h2 id="acct-end-title" className="sr-only">
          Sign out everywhere or delete your account
        </h2>
        <SignOutEverywhere runInProgress={runInProgress} />
        {account && (
          <DeleteAccountSection
            email={account.email ?? email}
            enabled={account.accounts_enabled}
            runInProgress={runInProgress}
            onDeleted={onDeleted}
          />
        )}
      </section>
    </>
  );
}

function IdentityCard({
  email,
  runInProgress,
  freeRuns,
}: {
  email: string | null;
  runInProgress: boolean;
  freeRuns: FreeRunsBanner | null;
}) {
  const [signingOut, setSigningOut] = useState(false);

  const handleSignOut = () => {
    if (signingOut || runInProgress) return;
    setSigningOut(true);
    void signOut().finally(() => setSigningOut(false));
  };

  return (
    <section className="key-card acct-identity" aria-label="Signed in as">
      <div className="acct-identity-details">
        <p className="acct-email">{email ?? "your account"}</p>
        <p className="key-help acct-identity-meta">
          Email sign-in
          {freeRuns !== null && (
            <>
              {" · "}
              <span className="acct-nowrap">
                {freeRuns.plan === "paid"
                  ? `Runs left this month: ${freeRuns.remaining} of ${freeRuns.limit}`
                  : freeRuns.scope === "account"
                    ? `Free runs left this month: ${freeRuns.remaining} of ${freeRuns.limit}`
                    : `Free runs left on this device: ${freeRuns.remaining}`}
              </span>
            </>
          )}
        </p>
      </div>
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
      {/* After the button, so on a phone the email and Sign out stay together. */}
      {runInProgress && <p className="pending-note acct-guard">{RUN_GUARD}</p>}
    </section>
  );
}

/* ---------------------------------------------------------------------- plan */

const INTERVAL_LABEL = { month: "Monthly", year: "Yearly" } as const;

/* One plan, so no pricing table: a sentence saying what it buys and the two
   ways to pay for it, or, once paid, what the account has and the one way to
   change it. Both leave for a Stripe-hosted page (`useBillingActions`);
   nothing here takes card details. */
function PlanGroup({ billing, paidMinutes }: { billing: BillingDetails; paidMinutes: number | null }) {
  const actions = useBillingActions();
  const paid = billing.plan === "paid";
  const month = billing.prices.month ? formatPrice(billing.prices.month) : null;
  const year = billing.prices.year ? formatPrice(billing.prices.year) : null;
  const extraRun = billing.prices.extraRun ? formatPrice(billing.prices.extraRun) : null;
  const periodEnd = billing.currentPeriodEnd ? formatLongDay(billing.currentPeriodEnd) : null;
  const paymentFailed = billing.status === "past_due" || billing.status === "unpaid";
  const busy = actions.busy !== null;

  const button = (action: BillingAction, label: string, primary: boolean) => (
    <button
      type="button"
      className={`btn ${primary ? "btn-primary" : "btn-secondary"} btn-pill`}
      onClick={() => void actions.run(action)}
      aria-disabled={busy || undefined}
    >
      {actions.busy === action ? "Opening…" : label}
    </button>
  );

  return (
    <section className="acct-group" aria-labelledby="acct-grp-plan">
      <h2 id="acct-grp-plan" className="history-group-label acct-group-label">
        Plan
      </h2>
      <div className="key-card acct-card acct-plan">
        {paid ? (
          <>
            <p className="acct-plan-name">
              Paid
              {billing.interval && <span className="acct-plan-interval"> · {INTERVAL_LABEL[billing.interval]}</span>}
            </p>
            {periodEnd && (
              <p className="key-help">{billing.cancelAtPeriodEnd ? `Ends ${periodEnd}` : `Renews ${periodEnd}`}</p>
            )}
            {paymentFailed && (
              <p className="error-note key-error acct-plan-warning">
                Payment failed — update your card in Manage billing.
              </p>
            )}
            <p className="key-help">
              <span className="acct-nowrap">
                {billing.runs.used} of {billing.runs.limit} used this month.
              </span>
              {extraRun && (
                <>
                  {" "}
                  <span className="acct-nowrap">Extra runs are {extraRun} each.</span>
                </>
              )}
            </p>
            <div className="key-actions">{button("portal", "Manage billing", paymentFailed)}</div>
          </>
        ) : (
          <>
            <p className="acct-plan-name">Free</p>
            <p className="key-help">
              The paid plan: {PAID_RUNS_PER_MONTH} runs a month on our key
              {paidMinutes !== null && `, videos up to ${paidMinutes} minutes`}, no key needed.
              {extraRun && ` Extra runs after that are ${extraRun} each.`}
            </p>
            {(month || year) && (
              <div className="key-actions">
                {month && button("month", `Upgrade — ${month}/month`, true)}
                {year && button("year", `Yearly — ${year}/year`, !month)}
              </div>
            )}
          </>
        )}
        {actions.error && (
          <p role="alert" className="error-note key-error">
            {actions.error}
          </p>
        )}
        <p role="status" className="key-status-slot">
          {actions.handedOff && (
            <span className="key-status">Opened in your browser. Come back here when you’re done.</span>
          )}
        </p>
      </div>
      {!paid && (
        <p className="key-help acct-group-note">
          Billed through Stripe. Cancel anytime. Runs with your own Gemini key never count.
        </p>
      )}
    </section>
  );
}

/* Ends every session, this device's last. A single click, like Sign out: it
   is undone by signing in again. The copy says what it cannot do: tokens are
   checked by signature only, so another device stays in until its access
   token expires, and API keys are a separate credential. */
function SignOutEverywhere({ runInProgress }: { runInProgress: boolean }) {
  const { phase, error, run } = useSignOutEverywhere();
  const helpId = useId();
  const errorId = useId();
  const working = phase === "working";

  return (
    <div className="acct-end-item">
      <button
        type="button"
        className="acct-link acct-end-control"
        onClick={() => {
          if (working || runInProgress) return;
          void run();
        }}
        aria-disabled={working || runInProgress || undefined}
        aria-describedby={error ? `${errorId} ${helpId}` : helpId}
      >
        {working ? "Signing out everywhere…" : "Sign out everywhere"}
      </button>
      <p id={helpId} className="key-help acct-end-help">
        Signs you out on every device. Others may stay signed in for up to an hour. API keys keep working
        until you revoke them.
      </p>
      {runInProgress && <p className="pending-note acct-guard">{RUN_GUARD}</p>}
      {error && (
        <div id={errorId} role="alert" className="error-inline acct-gap-sm">
          <p>{error}</p>
        </div>
      )}
      <p role="status" className="sr-only">
        {working ? "Signing out on every device…" : ""}
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ API keys */

type ApiKeysState = ReturnType<typeof useApiKeys>;

function ApiKeyManager({ enabled }: { enabled: boolean }) {
  /* The keys are fetched on the first opening only (`visited`), never on
     mount. The hook lives here, above the body, so the row can show a count
     once that fetch has answered and can flag a one-time secret that is
     still unseen when the row is collapsed. Collapsing keeps everything:
     the body stays mounted. */
  const [visited, setVisited] = useState(false);
  const [open, setOpen] = useState(false);
  const api = useApiKeys(enabled && visited);
  const active = api.keys?.filter((key) => key.active && !key.revoked_at).length ?? 0;
  const meta =
    api.justCreated && !open
      ? { text: "New key to copy", fresh: true }
      : api.keys && active > 0
        ? { text: active === 1 ? "1 key" : `${active} keys`, fresh: false }
        : null;

  return (
    <details
      className="key-card acct-card acct-disclosure"
      onToggle={(event) => {
        const isOpen = event.currentTarget.open;
        setOpen(isOpen);
        if (isOpen) setVisited(true);
      }}
    >
      <summary className="acct-row acct-disclosure-toggle">
        <span className="acct-row-text">
          <span className="acct-row-title">API keys</span>
          <span className="acct-row-description">Let your scripts and agents use VideoLens as you</span>
        </span>
        {meta && (
          <span className="acct-row-meta" data-fresh={meta.fresh ? "true" : undefined}>
            {meta.text}
          </span>
        )}
        <ChevronDown aria-hidden="true" />
      </summary>
      {visited && <ApiKeysSection enabled={enabled} api={api} />}
    </details>
  );
}

function AccountTabLink({ tab, title, description }: { tab: MainTab; title: string; description?: string }) {
  return (
    <Link href={mainTabHref(tab)} prefetch={false} className="acct-row" onClick={(event) => {
      if (!isPlainLeftClick(event)) return;
      event.preventDefault();
      goToMainTab(tab);
    }}>
      <span className="acct-row-text">
        <span className="acct-row-title">{title}</span>
        {description && <span className="acct-row-description">{description}</span>}
      </span>
      <ChevronRight aria-hidden="true" />
    </Link>
  );
}

/* The two link groups every state shows: plain rows, one tap to go. */
function AccountResources({ signedIn = false }: { signedIn?: boolean }) {
  return (
    <>
      <section className="acct-group" aria-labelledby="acct-grp-device">
        <h2 id="acct-grp-device" className="history-group-label acct-group-label">
          On this device
        </h2>
        <div className="key-card acct-card">
          <AccountTabLink tab="history" title="History" description="View or remove saved analyses" />
          <AccountTabLink
            tab="api-key"
            title="Your Gemini key"
            description="Your own Google key for analyses. Stays in this browser."
          />
        </div>
        {signedIn && <p className="key-help acct-group-note">Both stay in this browser when you sign out.</p>}
      </section>
      <section className="acct-group" aria-labelledby="acct-grp-help">
        <h2 id="acct-grp-help" className="history-group-label acct-group-label">
          Help
        </h2>
        <div className="key-card acct-card">
          <Link href="/privacy" prefetch={false} className="acct-row">
            <span className="acct-row-title">Privacy policy</span>
            <ChevronRight aria-hidden="true" />
          </Link>
          <Link href="/terms" prefetch={false} className="acct-row">
            <span className="acct-row-title">Terms of use</span>
            <ChevronRight aria-hidden="true" />
          </Link>
          <AccountTabLink tab="releases" title="What’s new" />
        </div>
      </section>
    </>
  );
}

function ApiKeysSection({ enabled, api }: { enabled: boolean; api: ApiKeysState }) {
  const { keys, loadError, actionError, busy, create, revoke, reload, justCreated, dismissSecret } = api;
  const [name, setName] = useState("");
  const [confirming, setConfirming] = useState<string | null>(null);
  const nameId = useId();
  const helpId = useId();

  if (!enabled) {
    return (
      <div className="acct-details-body">
        <p className="key-help acct-help-flush">This server does not keep accounts, so it cannot issue API keys.</p>
      </div>
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
    <section className="acct-details-body" aria-label="Manage API keys">
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
            placeholder="e.g. Claude Code"
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
        <p className="pending-note acct-empty">No API keys yet. Create one above to get started.</p>
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

/* ------------------------------------------------------------ delete account */

const RUN_GUARD_DELETE =
  "A run is in progress on Analyze. Wait until it finishes: deleting your account now would stop this screen following it.";

function DeleteAccountSection({
  email,
  enabled,
  runInProgress,
  onDeleted,
}: {
  email: string | null;
  enabled: boolean;
  runInProgress: boolean;
  onDeleted: (signedOut: Promise<void>) => void;
}) {
  const { state, remove, reset } = useAccountDeletion(onDeleted);
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const regionId = useId();
  const confirmId = useId();
  const confirmHelpId = useId();
  const errorId = useId();
  const toggleRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLInputElement>(null);
  const errorRef = useRef<HTMLDivElement>(null);
  const closedByCancel = useRef(false);

  /* The phrase to type is the account's email; with no email on record
     (not expected from an emailed-code sign-in) the word "delete" stands in. */
  const phrase = email ?? "delete";
  const matches = typed.trim().toLowerCase() === phrase.trim().toLowerCase();
  const deleting = state.phase === "deleting";
  const failed = state.phase === "failed" ? state : null;

  /* Focus follows the step: into the field on opening, back to the control
     that opened it on cancel, onto the message when the server refuses. */
  useEffect(() => {
    if (open) confirmRef.current?.focus();
    else if (closedByCancel.current) toggleRef.current?.focus();
  }, [open]);
  useEffect(() => {
    if (failed) errorRef.current?.focus();
  }, [failed]);

  if (!enabled) {
    return (
      <p className="key-help acct-end-item">
        This server does not keep accounts, so it cannot delete one. Ask us if you want your sign-in
        removed.
      </p>
    );
  }

  const cancel = () => {
    if (deleting) return;
    closedByCancel.current = true;
    setOpen(false);
    setTyped("");
    reset();
  };

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!matches || deleting || runInProgress) return;
    void remove();
  };

  /* Closed, a muted text link and nothing else: the page's last item. Open,
     the confirmation card takes its place. */
  if (!open) {
    return (
      <div className="acct-end-item">
        <button
          ref={toggleRef}
          type="button"
          className="acct-link acct-delete-link"
          aria-expanded={false}
          aria-controls={regionId}
          onClick={() => setOpen(true)}
        >
          Delete account…
        </button>
      </div>
    );
  }

  return (
    <section className="key-card acct-delete" aria-labelledby="acct-del-title">
      <h3 id="acct-del-title" className="acct-card-title">
        Delete account
      </h3>
      <p className="key-help">
        Removes your account from VideoLens for good. What is stored in this browser stays.
      </p>

      <form
        id={regionId}
        className="acct-delete-body"
        onSubmit={submit}
        noValidate
        aria-label="Confirm account deletion"
      >
        <div className="acct-delete-lists">
          <div>
            <h4 className="acct-delete-head">Deleted, and cannot be undone</h4>
            <ul className="acct-delete-list">
              <li>Your account and its workspace</li>
              <li>Every API key, so anything still using one stops working</li>
              <li>Any runs the server still holds for you (it keeps them an hour at most)</li>
            </ul>
          </div>
          <div>
            <h4 className="acct-delete-head">Kept, in this browser</h4>
            <ul className="acct-delete-list">
              <li>Your History</li>
              <li>Your own Gemini key</li>
            </ul>
            <p className="key-help acct-delete-note">
              Deleting your account does not clear this browser’s saved History or Gemini key.
              You can remove them under History and API key.
            </p>
          </div>
        </div>

        <label htmlFor={confirmId} className="key-label acct-delete-label">
          {email ? "Type your email to confirm" : "Type delete to confirm"}
        </label>
        <p id={confirmHelpId} className="key-help acct-help-top">
          It is <strong className="acct-strong">{phrase}</strong>. Capitals do not matter.
        </p>
        <input
          ref={confirmRef}
          id={confirmId}
          type={email ? "email" : "text"}
          inputMode={email ? "email" : "text"}
          autoComplete="off"
          autoCapitalize="off"
          autoCorrect="off"
          spellCheck={false}
          className="field acct-field"
          value={typed}
          onChange={(event) => setTyped(event.target.value)}
          aria-describedby={failed ? `${errorId} ${confirmHelpId}` : confirmHelpId}
        />

        {failed && (
          <div ref={errorRef} id={errorId} role="alert" tabIndex={-1} className="error-inline acct-gap-sm">
            <p>{failed.message}</p>
          </div>
        )}
        {runInProgress && <p className="pending-note acct-guard">{RUN_GUARD_DELETE}</p>}

        <div className="key-actions">
          <button
            type="submit"
            className="btn btn-pill acct-danger"
            aria-disabled={!matches || deleting || runInProgress || undefined}
          >
            {deleting ? "Deleting…" : "Delete my account"}
          </button>
          <button
            type="button"
            className="btn btn-secondary btn-pill key-remove"
            onClick={cancel}
            aria-disabled={deleting || undefined}
          >
            Cancel
          </button>
          <p role="status" className="key-status-slot">
            {deleting && <span className="key-status">Deleting your account…</span>}
          </p>
        </div>
      </form>
    </section>
  );
}

function DeletedCard({ signingOut, onBack }: { signingOut: boolean; onBack: () => void }) {
  const titleRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    titleRef.current?.focus();
  }, []);

  return (
    <section className="key-card" aria-labelledby="acct-gone-title">
      <h2 id="acct-gone-title" ref={titleRef} tabIndex={-1} className="acct-card-title acct-focus-title">
        Your account was deleted
      </h2>
      <p className="key-help">
        Your API keys no longer work and you are signed out on this device. Your History and your own
        Gemini key are still here in this browser.
      </p>
      <div className="key-actions">
        <button
          type="button"
          className="btn btn-secondary btn-pill key-remove"
          onClick={() => {
            if (!signingOut) onBack();
          }}
          aria-disabled={signingOut || undefined}
        >
          Back to sign in
        </button>
      </div>
      <p role="status" className="key-status-slot">
        {signingOut ? "Finishing sign-out on this device…" : ""}
      </p>
    </section>
  );
}
