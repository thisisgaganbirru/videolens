"use client";

import { useCallback, useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from "react";
import Link from "next/link";
import { Check, ChevronDown, ChevronRight, Copy } from "lucide-react";
import { useAccount, useAccountDeletion } from "@/application/useAccount";
import { useAccountHold, useAccountRestore } from "@/application/accountHold";
import type { SavedHistoryMode } from "@/application/useSavedHistory";
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
import { formatClockTime, formatDay, formatLongDay, formatPrice } from "@/components/format";
import type { ApiKeySummary, BillingDetails, Capability } from "@/domain/entities";
import type { FreeRunsBanner } from "@/application/useFreeRuns";
import { useBillingActions, type BillingAction, type CheckoutReturn } from "@/application/useBilling";
import { durationLabel, type MediaLimitsState } from "@/application/useMediaLimits";
import { HISTORY_LIMIT } from "@/application/useRunHistory";
import {
  ACCOUNT_FREE_RUNS_PER_DAY,
  PAID_EXTRA_RUNS_PER_MONTH,
  PAID_RUNS_PER_DAY,
} from "@/application/accountAllowance";

/* Hallmark · component: account panel · genre: editorial · theme: custom
 * (owner handoff, app/tokens.css) · layout: option A, grouped list (owner's
 * pick, 2026-11-09), refined 2026-11-14 (owner's six items): a compact
 * identity row, then small uppercase group labels over white grouped cards,
 * in the order Plan and usage · Upgrade or Billing · On this device ·
 * Developer tools · Information, then the quiet account-ending controls last
 * pre-emit critique: P4 H5 E4 S5 R5 V3
 * states: loading (capabilities or session not known yet) · unavailable ·
 *         signed out (lead reason, email, sending, code sent, verifying,
 *         field errors, resend countdown, run-in-progress guard, continue
 *         without an account, quiet extras) · signed in (account loading,
 *         rejected, failed + retry) · plan and usage (always, billing or
 *         not: plan name, runs left, video length, reset in local time; each
 *         static placeholder in each reserved slot until its read lands; own Gemini key
 *         variant; count unavailable) · upgrade (free + billing: comparison,
 *         price, one action, yearly as a quiet link, a null price hides its
 *         control, extra-run terms) · billing (paid: runs left, price,
 *         renews / ends, payment failed, extra-run terms, Manage billing) ·
 *         both: opening, handed off to the browser, action error, reserved
 *         static loading lines or unavailable text over the reserved
 *         stand-in while the plan is read · VideoLens API access (collapsed,
 *         count once known, unseen-secret flag, account loading, loading,
 *         load error, empty, list, creating, one-time secret, copied, revoke
 *         confirm, revoking, revoked, action error) · sign out everywhere
 *         (idle, run guard, working, failed and still signed in) · delete
 *         account (quiet link, confirming with typed email, run guard,
 *         deleting, failed: rejected / unavailable / unreachable / generic,
 *         not offered when the server keeps no accounts, deleted card) ·
 *         checkout return notice (confirming, paid, cancelled, unconfirmed,
 *         signed-out variant) · deletion hold (2026-11-14: held card with
 *         the date, restoring, restore failed, window closed, restored
 *         notice; deleted card with the restore-by date)
 *
 * Auth phases 2 and 3 (docs/frontend/auth-sign-in.md). Sign-in is optional
 * and the page says so: "Continue without an account" sits under the form.
 * The emailed code is the only method: Google is phase 4 and has no button.
 * Deletion is the very last item, a muted link that opens the form, and is
 * confirmed by typing the account's email.
 *
 * Two kinds of key appear here and the copy keeps them apart: a VideoLens
 * API key (ours, for other tools to submit runs as this account) and a
 * Gemini key (Google's, optional, the person's own). Neither is needed to
 * use the app.
 *
 * Components never touch the provider: the session, `/api/me` and
 * `/api/keys` all come through the three application hooks. */

type AccountPanelProps = {
  /** The deployment's `auth` capability row, from HomeScreen's one
   *  `/api/capabilities` read. Anything but `ok` means no sign-in form
   *  here; a leftover session can still sign out. */
  authCapability: Capability | null;
  /** That read has answered, success or failure. Until then the panel says
   *  "Loading" rather than "sign-in is not available", which it cannot know
   *  yet and which used to flash on every load. */
  capabilitiesSettled: boolean;
  /** True while a run is submitting, queued or processing on Analyze.
   *  Signing in or out changes who the server holds runs for, so the run on
   *  screen would stop answering (History keeps it: `recordGone`); the panel
   *  holds both actions until it settles. */
  runInProgress: boolean;
  /** The run allowance, from HomeScreen's one `useFreeRuns` read: the
   *  account's when the server counts it (`scope: "account"`, per UTC day),
   *  else this device's. Null when unknown, unlimited, or beside the point
   *  (a Gemini key is saved). */
  freeRuns: FreeRunsBanner | null;
  /** No key is saved and that read has not answered yet: the Plan and usage
   *  card keeps its rows and leaves the values blank. */
  freeRunsPending: boolean;
  /** The signed-in account's plan, from HomeScreen's one `useBilling` read.
   *  Null when billing is off, the server's `billing` capability is not
   *  `ok`, nobody is signed in, or the read failed: no Upgrade or Billing
   *  group. The Plan and usage card does not depend on it. */
  billing: BillingDetails | null;
  /** The server sells a plan and its answer for this account is still on
   *  the way: the Upgrade / Billing group's height is held meanwhile. */
  billingPending: boolean;
  /** A billing request failed; keep its reservation with an unavailable
   *  message, rather than treating the deployment as billing-disabled. */
  billingFailed: boolean;
  /** Set when this load came back from Stripe Checkout
   *  (`?billing=success|cancel`, already stripped from the address). */
  checkoutReturn: CheckoutReturn | null;
  /** The upload limits, from HomeScreen's one `useMediaLimits`: the length
   *  that applies to this person, the tiers the comparison quotes, and
   *  whether a Gemini key is saved. Lengths are never guessed: nothing is
   *  quoted until the read has answered. */
  limits: MediaLimitsState;
  /** Whether this account saves its runs (useSavedHistory, 2026-11-14):
   *  the History row under "On this device" says where runs are kept. */
  savedHistory?: SavedHistoryMode;
  /** The plan ended: saved runs are kept until this date. */
  savedUntil?: string | null;
};

const RUN_GUARD =
  "A run is in progress on Analyze. Wait until it finishes: signing in or out now would stop this screen following it until you switch back.";

export default function AccountPanel({
  authCapability,
  capabilitiesSettled,
  runInProgress,
  freeRuns,
  freeRunsPending,
  billing,
  billingPending,
  billingFailed,
  checkoutReturn,
  limits,
  savedHistory = "off",
  savedUntil = null,
}: AccountPanelProps) {
  const auth = useAuthUser();
  /* Held here, above the signed-in view: deleting signs out, which unmounts
     that view, and the confirmation has to outlive it. */
  /* "signing-out" until the stored session is cleared: going back to the
     sign-in view earlier would mount the signed-in view on the old token. */
  const [deleted, setDeleted] = useState<false | "signing-out" | "done">(false);
  /* The 30-day hold (2026-11-14): the day it ends, for the deleted card. */
  const [purgeAt, setPurgeAt] = useState<string | null>(null);
  const markDeleted = useCallback((signedOut: Promise<void>, until: string | null) => {
    setPurgeAt(until);
    setDeleted("signing-out");
    void signedOut.then(() => setDeleted((d) => (d ? "done" : d)));
  }, []);
  /* The same gate as the tab in HomeScreen: a provider in this build *and*
     the server's word that it verifies tokens. A failed report counts as
     no, so nobody signs in to a server that would refuse the token (the API
     client would not send it anyway). */
  const available = auth.enabled && authCapability?.state === "ok";
  /* Not known yet: the capability report, or (where sign-in works) who is
     signed in. Only the title and one line show, so nothing that appears
     later moves anything already on screen. */
  const loading = auth.enabled && (!capabilitiesSettled || (available && !auth.ready));

  return (
    <div className="key-page acct-page">
      <AppBackLink />
      <header className="view-head">
        <h1 className="view-title">Account</h1>
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
        <DeletedCard signingOut={deleted === "signing-out"} purgeAt={purgeAt} onBack={() => setDeleted(false)} />
      ) : loading ? (
        <p role="status" className="pending-note acct-gap">
          Loading…
        </p>
      ) : !available ? (
        <>
          <Unavailable />
          {/* A session left over from a server that did take sign-in: Sign
              out stays reachable here, at /app?view=account, even with the
              tab hidden. */}
          {auth.ready && auth.user && <IdentityRow email={auth.user.email} runInProgress={runInProgress} />}
        </>
      ) : auth.user ? (
        <SignedIn
          userId={auth.user.id}
          email={auth.user.email}
          runInProgress={runInProgress}
          freeRuns={freeRuns}
          freeRunsPending={freeRunsPending}
          billing={billing}
          billingPending={billingPending}
          billingFailed={billingFailed}
          limits={limits}
          onDeleted={markDeleted}
          savedHistory={savedHistory}
          savedUntil={savedUntil}
        />
      ) : (
        <SignedOut runInProgress={runInProgress} limits={limits} />
      )}
      {!loading && (deleted || !available || !auth.user) && (
        <>
          <DeviceGroup />
          <InformationGroup />
        </>
      )}
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

/* One reason first (the daily runs an account gives), then the form, then
   the way on without one. What else an account unlocks is true but not why
   most people sign in, so it comes last and quietly. Neither a Gemini key
   nor a VideoLens API key is needed to use the app, and nothing here says
   otherwise. */
function SignedOut({ runInProgress, limits }: { runInProgress: boolean; limits: MediaLimitsState }) {
  /* The length is the server's. Until its read answers, the line holds its
     place unseen (worded with the usual number, so the height is right)
     rather than quote one. */
  const minutes = limits.settled ? limits.byokMinutes : 10;
  return (
    <>
      <SignInCard runInProgress={runInProgress} />
      <p className="acct-continue-row">
        <Link
          href={mainTabHref("analyze")}
          prefetch={false}
          className="acct-link acct-continue"
          onClick={(event) => {
            if (!isPlainLeftClick(event)) return;
            event.preventDefault();
            goToMainTab("analyze");
          }}
        >
          Continue without an account
        </Link>
      </p>
      <p
        className={limits.settled ? "key-help acct-also" : "key-help acct-also acct-ghost"}
        aria-hidden={limits.settled ? undefined : true}
      >
        {minutes
          ? `An account also unlocks videos up to ${minutes} minutes with your own Gemini key, and VideoLens API keys for scripts and other tools.`
          : "An account also gives you VideoLens API keys for scripts and other tools."}
      </p>
    </>
  );
}

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
        <h2 className="acct-card-title">Get {ACCOUNT_FREE_RUNS_PER_DAY} free runs a day</h2>
        <p className="key-help acct-form-intro">
          Sign in or create an account with your email. No password needed.
        </p>
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
          We’ll email you a code. New here? Entering it creates your account.
        </p>
        <div className="key-actions">
          <button
            type="submit"
            className="btn btn-primary btn-pill acct-send-code"
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
  freeRunsPending,
  billing,
  billingPending,
  billingFailed,
  limits,
  onDeleted,
  savedHistory,
  savedUntil,
}: {
  userId: string;
  email: string | null;
  runInProgress: boolean;
  freeRuns: FreeRunsBanner | null;
  freeRunsPending: boolean;
  billing: BillingDetails | null;
  billingPending: boolean;
  billingFailed: boolean;
  limits: MediaLimitsState;
  onDeleted: (signedOut: Promise<void>, purgeAt: string | null) => void;
  savedHistory: SavedHistoryMode;
  savedUntil: string | null;
}) {
  const { account, problem, loading, reload } = useAccount(userId);
  /* The deletion hold (2026-11-14): `/api/me` says so, or any other read for
     this person was answered 410 first (the API client hears them all). */
  const hold = useAccountHold(userId);
  const restore = useAccountRestore(userId);
  const held =
    problem?.kind === "held" ? { purgeAt: problem.purgeAt ?? hold?.purgeAt ?? null } : hold;
  const identity = <IdentityRow email={account?.email ?? email} runInProgress={runInProgress} />;

  if (held && restore.state.phase !== "restored") {
    return (
      <>
        <HeldAccount
          email={account?.email ?? email}
          purgeAt={held.purgeAt}
          state={restore.state}
          runInProgress={runInProgress}
          onRestore={() => void restore.restore()}
        />
        <DeviceGroup />
        <InformationGroup />
      </>
    );
  }

  if (problem?.kind === "unavailable") {
    return (
      <>
        <Unavailable />
        {identity}
        <DeviceGroup />
        <InformationGroup />
      </>
    );
  }

  /* /api/me names the plan too, and usually lands before the run count and
     the plan: it lets the held stand-in below be the Billing card from the
     start for a paid account, instead of swapping from the taller Upgrade
     card (which moved every group under it). */
  const entitledPaid = account?.entitlement?.plan === "paid";
  const paid = billing?.plan === "paid" || freeRuns?.plan === "paid" || entitledPaid;

  return (
    <>
      {identity}

      {/* Said, not drawn: a line that came and went here pushed the page. */}
      <p role="status" className="sr-only">
        {loading ? "Loading your account…" : ""}
      </p>

      {/* After a restore: said once, in the plan notice's voice. */}
      {restore.state.phase === "restored" && (
        <p role="status" className="key-card acct-plan-notice acct-restored">
          Your account is back, on the free plan. Your saved runs are intact.
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

      <PlanUsageGroup
        freeRuns={freeRuns}
        freeRunsPending={freeRunsPending}
        billing={billing}
        billingPending={billingPending}
        billingFailed={billingFailed}
        entitledPaid={entitledPaid}
        limits={limits}
      />

      {billing && !billingFailed ? (
        billing.plan === "paid" ? (
          <BillingGroup billing={billing} />
        ) : (
          <UpgradeGroup billing={billing} limits={limits} />
        )
      ) : billingPending || billingFailed ? (
        /* Keep the existing stand-in's dimensions. Static loading lines or
           a failure message are painted over it without entering flow. */
        <div className="acct-loading-group" aria-busy={billingPending || undefined}>
          <div className="acct-ghost" aria-hidden="true" inert>
            {paid ? (
              <BillingGroup billing={billing ?? GHOST_PAID_BILLING} />
            ) : (
              <UpgradeGroup billing={billing ?? GHOST_FREE_BILLING} limits={limits} />
            )}
          </div>
          <div className="acct-loading-overlay" role="status">
            {billingFailed ? <p className="key-help">Billing unavailable.</p> : (
              <>
                <span className="sr-only">Loading billing</span>
                <PlaceholderLine /><PlaceholderLine /><PlaceholderLine />
              </>
            )}
          </div>
        </div>
      ) : null}

      <DeviceGroup signedIn saved={savedHistory} savedUntil={savedUntil} />

      {/* Drawn while `/api/me` is still loading too (the row is collapsed
          and fetches nothing until opened), so it does not arrive late and
          move Information down. */}
      {(account || loading) && (
        <section className="acct-group" aria-labelledby="acct-grp-dev">
          <h2 id="acct-grp-dev" className="history-group-label acct-group-label">
            Developer tools
          </h2>
          <ApiKeyManager
            key={userId}
            enabled={account ? account.accounts_enabled && account.workspace !== null : null}
          />
        </section>
      )}

      <InformationGroup />

      {/* Last on the page, on purpose: the two controls that end something. */}
      <section className="acct-end" aria-labelledby="acct-end-title">
        <h2 id="acct-end-title" className="sr-only">
          Security and account removal
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

/* Who is signed in, and the way out, on one line under the title. Sign out
   is a text control here, not a button: it has to stay within reach, but it
   is not what the page is for (owner, 2026-11-14). */
function IdentityRow({ email, runInProgress }: { email: string | null; runInProgress: boolean }) {
  const [signingOut, setSigningOut] = useState(false);

  const handleSignOut = () => {
    if (signingOut || runInProgress) return;
    setSigningOut(true);
    void signOut().finally(() => setSigningOut(false));
  };

  return (
    <section className="acct-id" aria-label="Signed in as">
      <p className="acct-email">{email ?? "your account"}</p>
      <button
        type="button"
        className="acct-link acct-signout"
        onClick={handleSignOut}
        aria-disabled={signingOut || runInProgress || undefined}
      >
        {signingOut ? "Signing out…" : "Sign out"}
      </button>
      {/* After the control, so the email and Sign out stay together. */}
      {runInProgress && <p className="pending-note acct-guard">{RUN_GUARD}</p>}
    </section>
  );
}

/* ------------------------------------------------------------ plan and usage */

/* What this account gets today: the plan, the runs left out of the limit,
   the video length that applies, and when the count resets. Drawn for every
   signed-in account, with billing or without (a free account on a server
   that sells nothing still has a plan and a count).

   Four reads feed it (session, run count, limits, plan) and none of them
   may move the page: the three rows are always there, and a value is left
   blank in its reserved line until its read has answered.

   The reset is the server's `resets_at` (UTC midnight) in the reader's own
   time zone, so it says "7:00 PM" in New York and "5:30 AM" in Mumbai. It
   never says "midnight" or "tomorrow": neither is true for most readers. */
function PlanUsageGroup({
  freeRuns,
  freeRunsPending,
  billing,
  billingPending,
  billingFailed,
  entitledPaid,
  limits,
}: {
  freeRuns: FreeRunsBanner | null;
  freeRunsPending: boolean;
  billing: BillingDetails | null;
  billingPending: boolean;
  billingFailed: boolean;
  /** The session's own entitlement (`/api/me`) says the plan is paid. */
  entitledPaid: boolean;
  limits: MediaLimitsState;
}) {
  const paid = billing?.plan === "paid" || freeRuns?.plan === "paid" || entitledPaid;
  /* Either read can name the plan; with both settled and silent (billing
     off, or a saved key so no count is read) the account is a free one.
     A failed plan read with no count is not silence: the plan is not known,
     and a paid account must not be told it is a free one. */
  const planKnown = freeRuns !== null || billing !== null || (!freeRunsPending && !billingPending);
  const planFailed = planKnown && billingFailed && freeRuns === null && billing === null && !entitledPaid;

  /* The run count's own read first; the plan's count stands in when that
     one failed. The plan read carries no reset instant. */
  const usage = freeRuns
    ? {
        remaining: freeRuns.remaining,
        limit: freeRuns.limit,
        monthly: freeRuns.period === "month",
        resetsAt: freeRuns.resetsAt,
        device: freeRuns.scope === "device",
      }
    : billing
      ? {
          remaining: Math.max(0, billing.runs.limit - billing.runs.used),
          limit: billing.runs.limit,
          monthly: billing.runs.period === "month",
          resetsAt: "",
          device: false,
        }
      : null;
  const ownKey = limits.hasKey;
  const waiting = !ownKey && usage === null && (freeRunsPending || billingPending);

  const runsValue = ownKey
    ? "On your own Gemini key"
    : usage
      ? `${usage.remaining} of ${usage.limit} runs left ${usage.monthly ? "this month" : "today"}`
      : waiting
        ? null
        : "Runs unavailable";

  /* The length follows the plan, so it waits for the plan as well as for
     the limits: a paid account must not read "3 minutes" for a moment. */
  const lengthKnown = limits.settled && planKnown;
  const onPaidTier = paid && limits.extended && limits.paidMinutes !== null;
  const lengthNote = !lengthKnown
    ? null
    : onPaidTier
      ? "No Gemini key needed"
      : limits.extended
        ? "With your own Gemini key"
        : limits.byokMinutes
          ? `or ${limits.byokMinutes} with your own Gemini key`
          : null;

  const resetWhen = usage
    ? usage.monthly
      ? usage.resetsAt && !Number.isNaN(Date.parse(usage.resetsAt))
        ? formatDay(usage.resetsAt)
        : null
      : formatClockTime(usage.resetsAt)
    : null;
  const resetValue = ownKey
    ? "No daily limit with your Gemini key"
    : resetWhen
      ? `${usage?.device ? "This browser · " : ""}Resets ${usage?.monthly ? "on" : "at"} ${resetWhen}`
      : "Reset time unavailable";

  return (
    <section className="acct-group acct-group-primary" aria-labelledby="acct-grp-plan">
      <h2 id="acct-grp-plan" className="history-group-label acct-group-label">
        Plan and usage
      </h2>
      <div className="key-card acct-card acct-plan">
        <p className="acct-plan-name">
          {planFailed ? "Plan unavailable" : planKnown ? (paid ? "Paid plan" : "Free account") : <PlaceholderLine />}
        </p>
        <dl className="acct-facts">
          <div className="acct-usage" aria-busy={waiting || undefined}>
            <dt className="sr-only">Runs</dt>
            <dd className="acct-usage-count" data-none={(!ownKey && !usage && !waiting) || undefined}>
              {runsValue ?? <><span className="sr-only">Loading runs</span><PlaceholderLine /></>}
            </dd>
            <dt className="sr-only">{ownKey ? "Daily limit" : "Reset time"}</dt>
            <dd className="acct-usage-reset">{waiting ? <PlaceholderLine /> : resetValue}</dd>
          </div>
          <div className="acct-fact">
            <dt>Video length</dt>
            <dd>{lengthKnown ? `Up to ${durationLabel(limits.limits.maxDurationSeconds)}` : <PlaceholderLine />}</dd>
            <dd className="acct-fact-note">{lengthNote}</dd>
          </div>
        </dl>
      </div>
    </section>
  );
}

function PlaceholderLine() {
  return <span className="acct-placeholder" aria-hidden="true" />;
}

/* ------------------------------------------------------- upgrade and billing */

/* Stand-ins for the group's reserved height while the plan is read (see
   SignedIn). Never seen and never announced; the prices only size the lines
   they would fill. */
const GHOST_FREE_BILLING: BillingDetails = {
  enabled: true,
  plan: "free",
  status: null,
  interval: null,
  currentPeriodEnd: null,
  cancelAtPeriodEnd: false,
  runs: { limit: ACCOUNT_FREE_RUNS_PER_DAY, used: 0, period: "day" },
  extraRuns: null,
  prices: { month: { amount: 1200, currency: "usd" }, year: null, extraRun: { amount: 15, currency: "usd" } },
};
const GHOST_PAID_BILLING: BillingDetails = {
  ...GHOST_FREE_BILLING,
  plan: "paid",
  status: "active",
  interval: "month",
  currentPeriodEnd: "2026-12-13T00:00:00Z",
  runs: { limit: PAID_RUNS_PER_DAY, used: 0, period: "day" },
  /* Reserves the "Extra runs this month" row, including older servers. */
  extraRuns: { used: 0, limit: PAID_EXTRA_RUNS_PER_MONTH, period: "month", resetsAt: null },
};

function extraRunTerms(included: number, extraRun: string | null): string {
  return extraRun
    ? `Past the ${included}, extra runs are ${extraRun} each, up to ${PAID_EXTRA_RUNS_PER_MONTH} a month.`
    : `Past the ${included}, extra runs are billed per run, up to ${PAID_EXTRA_RUNS_PER_MONTH} a month.`;
}

/* What the two billing groups share under their own content: the action's
   failure and the note that Stripe opened elsewhere (the installed app). */
function BillingActionStatus({ actions }: { actions: ReturnType<typeof useBillingActions> }) {
  return (
    <>
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
    </>
  );
}

/* A free account where the server sells the plan: the two tiers side by
   side, the price, one action, and the extra-run terms on their own line.

   The length row is exact on purpose (owner, 2026-11-14). A free account's
   included runs need no Gemini key either, so "no key needed" is not a paid
   benefit in general; the one thing only the paid plan has is longer videos
   *without* a key. The free column therefore says what a key adds, and the
   paid column ties "no key" to the length. Never "unlimited": the extra
   runs are priced and capped, and both are stated.

   The free count is the server's (`runs.limit` on a free body is the free
   allowance); the paid 30 and the 200 cap are the sold constants, because
   no body a free account can read carries them. */
function UpgradeGroup({ billing, limits }: { billing: BillingDetails; limits: MediaLimitsState }) {
  const actions = useBillingActions();
  const month = billing.prices.month ? formatPrice(billing.prices.month) : null;
  const year = billing.prices.year ? formatPrice(billing.prices.year) : null;
  const extraRun = billing.prices.extraRun ? formatPrice(billing.prices.extraRun) : null;
  const busy = actions.busy !== null;
  const primary: BillingAction = month ? "month" : "year";

  return (
    <section className="acct-group" aria-labelledby="acct-grp-upgrade">
      <h2 id="acct-grp-upgrade" className="history-group-label acct-group-label">
        Upgrade
      </h2>
      <div className="key-card acct-card acct-plan">
        <table className="acct-compare">
          <caption className="sr-only">Your free account compared with the paid plan</caption>
          <thead>
            <tr>
              <th scope="col">Your free account</th>
              <th scope="col">Paid plan</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <th scope="rowgroup" colSpan={2}>
                Runs a day
              </th>
            </tr>
            <tr>
              <td>
                <strong className="acct-figure">{billing.runs.limit}</strong>
              </td>
              <td>
                <strong className="acct-figure">{PAID_RUNS_PER_DAY}</strong>
              </td>
            </tr>
          </tbody>
          {/* Saved history (2026-11-14): where runs are kept, per plan. */}
          <tbody>
            <tr>
              <th scope="rowgroup" colSpan={2}>
                History
              </th>
            </tr>
            <tr>
              <td>
                <strong>Last {HISTORY_LIMIT}</strong> in this browser
              </td>
              <td>
                <strong>Saved to your account</strong> on every device
              </td>
            </tr>
          </tbody>
          {/* Only where the server reports the paid tier's length: the
              comparison never quotes a number it has not heard. */}
          {limits.paidMinutes !== null && (
            <tbody>
              <tr>
                <th scope="rowgroup" colSpan={2}>
                  Video length
                </th>
              </tr>
              <tr>
                <td>
                  <strong>Up to {durationLabel(limits.standardSeconds)}</strong>
                  {limits.byokMinutes !== null && <> or {limits.byokMinutes} with your own Gemini key</>}
                </td>
                <td>
                  <strong>Up to {limits.paidMinutes} minutes</strong> with no Gemini key
                </td>
              </tr>
            </tbody>
          )}
        </table>

        {(month || year) && (
          <>
            <p className="acct-price">
              {month ? (
                <>
                  <strong>{month}</strong> a month
                </>
              ) : (
                <>
                  <strong>{year}</strong> a year
                </>
              )}
            </p>
            <div className="key-actions">
              <button
                type="button"
                className="btn btn-primary btn-pill"
                onClick={() => void actions.run(primary)}
                aria-disabled={busy || undefined}
              >
                {actions.busy === primary ? "Opening…" : "Upgrade to paid"}
              </button>
              {month && year && (
                <button
                  type="button"
                  className="acct-link acct-yearly"
                  onClick={() => void actions.run("year")}
                  aria-disabled={busy || undefined}
                >
                  {actions.busy === "year" ? "Opening…" : `Or pay ${year} a year`}
                </button>
              )}
            </div>
          </>
        )}
        <p className="key-help acct-extra-terms">{extraRunTerms(PAID_RUNS_PER_DAY, extraRun)}</p>
        <BillingActionStatus actions={actions} />
      </div>
      <p className="key-help acct-group-note">
        Billed through Stripe. Cancel anytime. Runs with your own Gemini key never count.
      </p>
    </section>
  );
}

/* A paid account: what it has and the one way to change it. Only what
   `GET /api/billing` returns is shown. It carries no count of extra runs
   used this month, so none is drawn; the terms line states the price and
   the cap instead. Runs left today is in the Plan and usage card directly
   above, so it is not repeated here. Leaves for Stripe's hosted portal; nothing here takes
   card details. */
function BillingGroup({ billing }: { billing: BillingDetails }) {
  const actions = useBillingActions();
  const price = billing.interval ? billing.prices[billing.interval] : null;
  const amount = price ? formatPrice(price) : null;
  const extraRun = billing.prices.extraRun ? formatPrice(billing.prices.extraRun) : null;
  const periodEnd = billing.currentPeriodEnd ? formatLongDay(billing.currentPeriodEnd) : null;
  const paymentFailed = billing.status === "past_due" || billing.status === "unpaid";

  return (
    <section className="acct-group" aria-labelledby="acct-grp-billing">
      <h2 id="acct-grp-billing" className="history-group-label acct-group-label">
        Billing
      </h2>
      <div className="key-card acct-card acct-plan">
        {paymentFailed && (
          <p className="error-note key-error acct-plan-warning">
            Payment failed. Update your card in Manage billing.
          </p>
        )}
        <dl className="acct-facts acct-facts-flush">
          {billing.interval && (
            <div className="acct-fact">
              <dt>Price</dt>
              <dd>
                {amount
                  ? `${amount} a ${billing.interval}`
                  : billing.interval === "year"
                    ? "Billed yearly"
                    : "Billed monthly"}
              </dd>
            </div>
          )}
          {periodEnd && (
            <div className="acct-fact">
              <dt>{billing.cancelAtPeriodEnd ? "Ends" : "Renews"}</dt>
              <dd>{periodEnd}</dd>
            </div>
          )}
          {/* The server's own count and cap (2026-11-14). No limit means the
              cap is off: the count alone, never an invented number. */}
            <div className={billing.extraRuns ? "acct-fact" : "acct-fact acct-ghost"} aria-hidden={!billing.extraRuns || undefined}>
              <dt>Extra runs this month</dt>
              <dd>
                {billing.extraRuns
                  ? billing.extraRuns.limit === null
                    ? billing.extraRuns.used
                    : `${billing.extraRuns.used} of ${billing.extraRuns.limit}`
                  : "—"}
              </dd>
            </div>
        </dl>
        <p className="key-help acct-extra-terms">{extraRunTerms(billing.runs.limit, extraRun)}</p>
        <div className="key-actions">
          <button
            type="button"
            className={`btn ${paymentFailed ? "btn-primary" : "btn-secondary"} btn-pill`}
            onClick={() => void actions.run("portal")}
            aria-disabled={actions.busy !== null || undefined}
          >
            {actions.busy === "portal" ? "Opening…" : "Manage billing"}
          </button>
        </div>
        <BillingActionStatus actions={actions} />
      </div>
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

/* `enabled` is null while `/api/me` is still loading: the row is drawn
   anyway (collapsed, it asks for nothing), and opening it then says so. */
function ApiKeyManager({ enabled }: { enabled: boolean | null }) {
  /* The keys are fetched on the first opening only (`visited`), never on
     mount. The hook lives here, above the body, so the row can show a count
     once that fetch has answered and can flag a one-time secret that is
     still unseen when the row is collapsed. Collapsing keeps everything:
     the body stays mounted. */
  const [visited, setVisited] = useState(false);
  const [open, setOpen] = useState(false);
  const api = useApiKeys(enabled === true && visited);
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
          <span className="acct-row-title">VideoLens API access</span>
          <span className="acct-row-description">
            VideoLens API keys let other tools submit runs through your account.
          </span>
        </span>
        {meta && (
          <span className="acct-row-meta" data-fresh={meta.fresh ? "true" : undefined}>
            {meta.text}
          </span>
        )}
        <ChevronDown aria-hidden="true" />
      </summary>
      {visited &&
        (enabled === null ? (
          <div className="acct-details-body">
            <p role="status" className="pending-note acct-help-flush">
              Loading your account…
            </p>
          </div>
        ) : (
          <ApiKeysSection enabled={enabled} api={api} />
        ))}
    </details>
  );
}

function AccountTabLink({ tab, title, description }: { tab: MainTab; title: ReactNode; description?: string }) {
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

/* The two link groups every state shows: plain rows, one tap to go. Signed
   in, Developer tools sits between them. */
function DeviceGroup({
  signedIn = false,
  saved = "off",
  savedUntil = null,
}: {
  signedIn?: boolean;
  saved?: SavedHistoryMode;
  savedUntil?: string | null;
}) {
  /* Saved history (2026-11-14): a paid account's runs live on the account,
     so the row says so instead of "this browser". */
  const until = savedUntil && !Number.isNaN(new Date(savedUntil).getTime()) ? formatLongDay(savedUntil) : null;
  const onAccount = saved === "saving" || saved === "window";
  const historyLine =
    saved === "saving"
      ? "Saved to your account · On every device"
      : saved === "window"
        ? until
          ? `Saved to your account until ${until}`
          : "Saved to your account for 30 days"
        : `Saved in this browser · Up to ${HISTORY_LIMIT} runs`;
  return (
    <section className="acct-group" aria-labelledby="acct-grp-device">
      <h2 id="acct-grp-device" className="history-group-label acct-group-label">
        On this device
      </h2>
      <div className="key-card acct-card">
        <AccountTabLink
          tab="history"
          title={onAccount ? "History" : "Recent history"}
          description={historyLine}
        />
        <AccountTabLink
          tab="api-key"
          title={
            <>
              Your Gemini key <span className="acct-optional">(optional)</span>
            </>
          }
          description="Use your own Google AI access."
        />
      </div>
      <p className="key-help acct-group-note">
        {onAccount
          ? "Your Gemini key is not synced. It stays in this browser when you sign out."
          : `Not synced between devices.${signedIn ? " Both stay in this browser when you sign out." : ""}`}
      </p>
    </section>
  );
}

/* No support or contact row: there is no monitored address yet. */
function InformationGroup() {
  return (
    <section className="acct-group acct-group-information" aria-labelledby="acct-grp-info">
      <h2 id="acct-grp-info" className="history-group-label acct-group-label">
        Information
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
        <p className="key-help acct-help-flush">
          This server does not keep accounts, so it cannot issue VideoLens API keys.
        </p>
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
    <section className="acct-details-body" aria-label="Manage VideoLens API keys">
      <p className="key-help acct-help-top">
        A VideoLens API key lets a script or an agent call the VideoLens API as you. Send it in an{" "}
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
        <p className="pending-note acct-empty">No VideoLens API keys yet. Create one above to get started.</p>
      ) : (
        <ul className="acct-key-list" aria-label="Your VideoLens API keys">
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
  onDeleted: (signedOut: Promise<void>, purgeAt: string | null) => void;
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
        Your account stops working now and is kept for 30 days, in case you change your mind. After
        that it is removed for good. What is stored in this browser stays.
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
            <h4 className="acct-delete-head">Stops now, removed after 30 days</h4>
            <ul className="acct-delete-list">
              <li>Your account and its workspace</li>
              <li>Every run saved to your account</li>
              <li>Every API key, so anything still using one stops working</li>
              <li>Your paid plan, if you have one: the subscription is cancelled now</li>
            </ul>
            <p className="key-help acct-delete-note">
              To restore it, sign in again with the same email within 30 days. It comes back on the
              free plan, with its saved runs. Until then that email cannot start a new account.
            </p>
          </div>
          <div>
            <h4 className="acct-delete-head">Kept, in this browser</h4>
            <ul className="acct-delete-list">
              <li>Your History</li>
              <li>Your own Gemini key</li>
            </ul>
            <p className="key-help acct-delete-note">
              Deleting your account does not clear this browser’s saved History or Gemini key.
              You can remove them under History and Gemini key.
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

function DeletedCard({
  signingOut,
  purgeAt,
  onBack,
}: {
  signingOut: boolean;
  /** The day the 30-day hold ends; null from an older server that removed
   *  the account at once. */
  purgeAt: string | null;
  onBack: () => void;
}) {
  const until = purgeAt && !Number.isNaN(new Date(purgeAt).getTime()) ? formatLongDay(purgeAt) : null;
  const titleRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    titleRef.current?.focus();
  }, []);

  return (
    <section className="key-card" aria-labelledby="acct-gone-title">
      <h2 id="acct-gone-title" ref={titleRef} tabIndex={-1} className="acct-card-title acct-focus-title">
        Your account was deleted
      </h2>
      {until ? (
        <p className="key-help">
          It stopped working now, your API keys with it, and you are signed out on this device. Sign in
          again with the same email before {until} to restore it. After that it is removed for good. Your
          History and your own Gemini key are still here in this browser.
        </p>
      ) : (
        <p className="key-help">
          Your API keys no longer work and you are signed out on this device. Your History and your own
          Gemini key are still here in this browser.
        </p>
      )}
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

/* ------------------------------------------------------------ deletion hold */

/* Signed in to an account that was deleted less than 30 days ago (410
   `account_pending_deletion`, 2026-11-14). The one thing to decide is
   whether to bring it back, so that is the page's one filled action; Sign
   out is the way to leave it be (and use the app without an account, which
   keeps working). `closed`: the 30 days have passed (410
   `restore_window_closed`), so only Sign out is left. */
function HeldAccount({
  email,
  purgeAt,
  state,
  runInProgress,
  onRestore,
}: {
  email: string | null;
  purgeAt: string | null;
  state: ReturnType<typeof useAccountRestore>["state"];
  runInProgress: boolean;
  onRestore: () => void;
}) {
  const [signingOut, setSigningOut] = useState(false);
  const titleRef = useRef<HTMLHeadingElement>(null);
  const until = purgeAt && !Number.isNaN(new Date(purgeAt).getTime()) ? formatLongDay(purgeAt) : null;
  const restoring = state.phase === "restoring";
  const closed = state.phase === "closed";

  useEffect(() => {
    if (closed) titleRef.current?.focus();
  }, [closed]);

  const leave = () => {
    if (signingOut || restoring || runInProgress) return;
    setSigningOut(true);
    void signOut().finally(() => setSigningOut(false));
  };

  return (
    <section className="key-card acct-held" aria-labelledby="acct-held-title">
      <h2 id="acct-held-title" ref={titleRef} tabIndex={-1} className="acct-card-title acct-focus-title">
        {closed ? "This account can no longer be restored" : "This account is scheduled for deletion"}
      </h2>
      {closed ? (
        <p className="key-help">
          The 30 days to restore it have passed, so it is being removed for good. Sign out to keep using
          VideoLens without an account. Once it is gone, signing in with the same email starts a new one.
        </p>
      ) : (
        <>
          <p className="key-help">
            {email ? (
              <>
                <strong className="acct-strong">{email}</strong> was deleted.{" "}
              </>
            ) : (
              "This account was deleted. "
            )}
            {until
              ? `It is kept until ${until}, then removed for good, with every run saved to it.`
              : "It is kept for 30 days after it was deleted, then removed for good, with every run saved to it."}
          </p>
          <p className="key-help acct-held-more">
            Restore it to keep using it. It comes back on the free plan, with its saved runs.
          </p>
        </>
      )}
      {state.phase === "failed" && (
        <div role="alert" className="error-inline acct-gap-sm">
          <p>{state.message}</p>
        </div>
      )}
      {runInProgress && <p className="pending-note acct-guard">{RUN_GUARD}</p>}
      <div className="key-actions">
        {!closed && (
          <button
            type="button"
            className="btn btn-primary btn-pill"
            onClick={() => {
              if (!restoring && !signingOut) onRestore();
            }}
            aria-disabled={restoring || signingOut || undefined}
          >
            {restoring ? "Restoring…" : "Restore account"}
          </button>
        )}
        <button
          type="button"
          className={closed ? "btn btn-primary btn-pill" : "btn btn-secondary btn-pill key-remove"}
          onClick={leave}
          aria-disabled={signingOut || restoring || runInProgress || undefined}
        >
          {signingOut ? "Signing out…" : "Sign out"}
        </button>
        <p role="status" className="key-status-slot">
          {restoring ? <span className="key-status">Restoring your account…</span> : null}
        </p>
      </div>
    </section>
  );
}
