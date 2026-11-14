"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import AppNav from "@/components/AppNav";
import { accountEntryFrom } from "@/application/useAccountEntry";
import BottomTabBar from "@/components/BottomTabBar";
import SiteFooter from "@/components/SiteFooter";
import CapabilityNotice from "@/components/CapabilityNotice";
import FreeRunsBanner from "@/components/FreeRunsBanner";
import type { FreeRunsBanner as FreeRunsBannerState } from "@/application/useFreeRuns";
import ReachabilityNotice from "@/components/ReachabilityNotice";
import { useServerReachability } from "@/application/serverReachability";
import { revalidateFreeRuns, useFreeRuns } from "@/application/useFreeRuns";
import UploadForm, { type IntakeHandoff } from "@/components/UploadForm";
import { MEDIA_FILE_ACCEPT, readTermsAccepted } from "@/components/mediaTerms";
import RunStatusView from "@/components/RunStatusView";
import ResultsView, { FileSourceCard, SourceCard, creatorInitials } from "@/components/ResultsView";
import ApiKeyPanel from "@/components/panels/ApiKeyPanel";
import HistoryPanel from "@/components/panels/HistoryPanel";
import VersionLogPanel from "@/components/panels/VersionLogPanel";
import AccountPanel from "@/components/panels/AccountPanel";
import { useAnalysisRun } from "@/application/useAnalysisRun";
import { refreshSavedHistory, useSavedHistory } from "@/application/useSavedHistory";
import { HISTORY_LIMIT, useHistoryBoot } from "@/application/useRunHistory";
import { useDocumentTitle } from "@/application/useDocumentTitle";
import { useCapabilities } from "@/application/useCapabilities";
import { useAuthUser, useStoredSessionHint } from "@/application/useAuthSession";
import { useMediaLimits } from "@/application/useMediaLimits";
import { useBilling } from "@/application/useBilling";
import { formatPrice } from "@/components/format";
import { useSharedUrl, type SharedUrl } from "@/application/useSharedUrl";
import { canonicalizeAppPath, goToMainTab, useMainTab, type MainTab } from "@/application/useMainTab";
import type { RunSourceKind, SavedRunSummary } from "@/domain/entities";
import { platformName } from "@/domain/platforms";

/**
 * The app shell for one tab.
 *
 * Takes the tab as a prop rather than reading the URL itself, so it can be
 * rendered both as the resolved route and as `app/page.tsx`'s Suspense
 * fallback — the fallback is what gets baked into the prerendered HTML, and it
 * has to be a real Analyze view, not a placeholder.
 */
/* The stand-in the free-runs slot sizes itself with before the first read
   (2026-11-14, Android QA run 22): a signed-out device with runs left and
   sign-in offered, the first-visit case and the longest "runs left" line, so
   the real strip is the same height or a line shorter, never taller. Never
   seen: the slot hides it and it is inert. */
const FREE_RUNS_GHOST: FreeRunsBannerState = {
  scope: "device",
  period: "day",
  plan: "free",
  remaining: 3,
  limit: 3,
  exhausted: false,
  overage: false,
  /* A valid time, so the stand-in carries the "Resets at …" sentence and is
     as long as the real strip (UX fix spec 3.2). */
  resetsAt: "2026-01-01T00:00:00Z",
};

export default function HomeScreen({ activeTab }: { activeTab: MainTab }) {
  const [sourceOpen, setSourceOpen] = useState(false);
  const {
    status,
    stage,
    sourceKind,
    mediaKind,
    freeRunRefunded,
    result,
    completeness,
    sourceMetadata,
    error,
    submitting,
    sourceName,
    durationSeconds,
    canRetry,
    expired,
    expiredReason,
    againUrl,
    reconnectIn,
    reconnecting,
    reconnectAttempt,
    lostCause,
    submit,
    retry,
    reconnectNow,
    reset,
    openRun,
    openSavedRun,
    resume,
  } = useAnalysisRun();

  /* Refinement 6 (RUN-06 web): a reload mid-run comes back to that run, not
     to a fresh intake. Once per mount (`resume` is stable), and declared before `useSharedUrl`
     below on purpose: effects run in order, so this sees a shared link
     before that hook consumes it (and steps aside). A share arriving later
     still wins — its reset drops the resumed run. */
  useEffect(() => {
    resume();
  }, [resume]);

  /* Refinement 9 (item 9): in the installed app, `/app` reached by a
     client-side link becomes `/app.html`, the address every other way in
     already lands on. A no-op on the web. */
  useEffect(() => {
    canonicalizeAppPath();
  }, []);

  /* Called here, once, rather than in the three components that consume it.
     This component is never unmounted by a tab switch (the tabs are a
     `pushState` query param), so one call is one request per app load; three
     calls in three conditionally-rendered children would be one request per
     tab visit. The two contextual notices therefore take props instead of
     reaching for the hook themselves. */
  const {
    notice,
    urlDownload,
    dailyBudget,
    auth: authCapability,
    billing: billingCapability,
    settled: capabilitiesSettled,
  } = useCapabilities();

  const sharedUrl = useSharedUrl();

  /* Here for the same reason as `useCapabilities`: this shell is never
     unmounted by a tab switch, so the allowance is read once per app load
     (and again after each run, on a 402, or when the key is removed). */
  /* Auth phase 2: who is signed in (declared here because the free-run
     allowance depends on it). History re-imports the server's runs when a
     person signs in (useHistoryBoot, below), and the Account tab is offered
     only where sign-in actually works. Signed in, the server counts the
     account's free runs instead of this device's (2026-11-13), so
     a sign-in or sign-out re-reads the allowance. */
  const authUser = useAuthUser();
  const storedSessionHint = useStoredSessionHint();
  const freeRuns = useFreeRuns(authUser.ready ? (authUser.user?.id ?? "") : null);

  /* Refinement 9 (items 6 and 8, device QA): every time the intake comes
     back — "Analyze another file" after a refunded run, stop watching, a
     failed open — read the allowance again, so the banner never shows the
     count from before the last run. Launch is covered too (deduplicated with
     useFreeRuns' own first read). A no-op on the user's own key. */
  useEffect(() => {
    if (status === "idle") void revalidateFreeRuns();
  }, [status]);

  /* Refinement 4 (LCH-06): both reads above go quiet when they fail, which
     made an unreachable server look exactly like a healthy one. This watches
     them (and navigator.onLine), says so on Analyze, and retries them quietly
     when the connection may be back. Never blocks the form. */
  const reachability = useServerReachability();
  /* Once per app load: seed History from the server the first time, and
     re-check runs this browser last saw unfinished. Here, not in the History
     panel, because it has to happen whichever tab the app opens on. */
  /* The Account tab is offered only where sign-in actually works: a
     provider is configured in this build *and* the server says it verifies
     tokens. */
  useHistoryBoot({ ready: authUser.ready, userId: authUser.user?.id ?? null });
  /* Shared with every other route (useAccountEntry): the gate, plus the top
     bar's control: a "Sign in" pill signed out, the signed-in person's
     initial (null, no email: the person glyph), nothing until the session is
     known. */
  const { showAccount, accountState, accountInitial } = accountEntryFrom(authUser, authCapability);
  /* The paid plan (2026-11-13): read only where sign-in works and the
     server's `billing` capability is `ok`, for whoever is signed in. With
     billing off nothing is requested and `billing` stays null, so every
     screen looks as it did before billing existed. */
  const { billing, notice: checkoutReturn, pending: billingPending, failed: billingFailed } = useBilling(
    authUser.ready ? (authUser.user?.id ?? null) : null,
    showAccount && billingCapability?.state === "ok"
  );
  /* Either read can say so first: the plan, or the free-run count (which
     carries `plan` too, and is the one read while no key is saved). */
  const paid = billing?.plan === "paid" || freeRuns.banner?.plan === "paid";
  const extraRunPrice = billing?.prices.extraRun ? formatPrice(billing.prices.extraRun) : null;
  /* Paid saved history (2026-11-14): whether this account saves its runs,
     read once someone is signed in where sign-in works. Off for everyone
     else, and on a backend without the routes, so nothing changes there. */
  const savedHistory = useSavedHistory(authUser.ready ? (authUser.user?.id ?? null) : null, showAccount, paid);
  const savingRuns = savedHistory.mode === "saving";
  /* Upload limits (2026-11-13): the paid plan, or signed in on their own key,
     gets the larger tier. Read once per app load here, recomputed on
     sign-in/out, on a plan change, and when the key is saved or removed. The
     sign-in hint is offered only where sign-in works, to someone with a key
     saved who is signed out. */
  const mediaLimits = useMediaLimits(Boolean(authUser.user), paid);
  const signInForMinutes =
    showAccount && authUser.ready && !authUser.user && mediaLimits.hasKey ? mediaLimits.upgradeMinutes : null;
  /* Signing in or out changes who owns runs on the server, so a run being
     watched would stop answering. The Account panel holds both meanwhile. */
  const runInProgress = submitting || status === "queued" || status === "processing";
  /* The strip and the out-of-runs offer both depend on whether sign-in is
     offered, which is known only once the capabilities read and the session
     have answered. Until then the slot keeps its stand-in, so the strip
     never lands short and then grows a "Sign in" sentence (a measured 0.037
     layout shift at 412 px, UX fix spec 3.6). */
  const stripKnown = capabilitiesSettled && authUser.ready;
  /* The Gemini key page's "Sign in" line needs the session, the auth
     capability and `/api/limits`. It is known not to apply as soon as any of
     them says so (no provider in this build, someone signed in, sign-in not
     offered); otherwise its space is held until all three have answered.
     A session stored on this device counts as signed in for this purpose,
     so a signed-in visit never holds the line while the provider loads.
     What still moves once: the server turning sign-in off, `/api/limits`
     failing, or a stored session that turns out to be expired. */
  const keySignInPending =
    authUser.enabled &&
    !(authUser.ready ? authUser.user : storedSessionHint) &&
    !(capabilitiesSettled && !showAccount) &&
    !(capabilitiesSettled && authUser.ready && mediaLimits.settled);

  /* A link shared into the app is a request to analyze *that*, so it takes the
     screen over: whatever tab is showing, and whatever run is on it, gives way
     to a fresh intake with the link filled in. The analysis is not started for
     the user — an accidental share should not spend a run — so the only thing
     left to do is press analyze.

     This has to live here rather than in `UploadForm`, which is mounted only
     while the run state is idle. When it owned the share listener, a link
     shared while a finished result was up reached nobody: it stayed in
     localStorage until a back press remounted the form, which is why the app
     went on showing the previous video's results and then produced the old link
     as a prefill on the way out. */
  useEffect(() => {
    if (!sharedUrl) return;
    goToMainTab("analyze");
    reset();
  }, [sharedUrl, reset]);

  /* An error while the pipeline is on screen can only come from the poll's
     catch — `submit` stays on idle until the server answers, and `openRun`
     returns to idle on failure. So this is precisely "the poll is down":
     `useAnalysisRun` is counting down to its next reconnect attempt, and
     nothing on screen advances until one succeeds (which clears `error` and
     drops this flag on its own). */
  const connectionLost = Boolean(error) && (status === "queued" || status === "processing");
  /* An uploaded file's Source card (refinement 2, #6): only for a file run,
     and only when there is something true to show — the name this browser
     picked, or the length the run detail reported. */
  const fileSource =
    !sourceMetadata && sourceKind === "file" && (sourceName || durationSeconds !== null)
      ? { name: sourceName, durationSeconds }
      : null;

  /* What the intake's link field starts with (refinement 1, #7 and #14). Two
     sources: a link shared into the app, and "Analyze it again" on an expired
     run. The newer one wins. A share that has already been used is dismissed
     when the user starts over, so "Analyze another file" after a shared-link
     run comes back to an empty field instead of the old link (the form
     remounts on reset and would otherwise take the same share again). Derived
     during render, no effect: the form itself applies whatever it is handed. */
  const [againPrefill, setAgainPrefill] = useState<SharedUrl | null>(null);
  const [fromHistory, setFromHistory] = useState(false);
  /* Opened from the account's saved runs, rather than this browser's own
     (2026-11-14): decides which "where it is kept" line the result shows. */
  const [openedSaved, setOpenedSaved] = useState(false);
  const [dismissedShare, setDismissedShare] = useState<SharedUrl | null>(null);
  const liveShare = sharedUrl && sharedUrl !== dismissedShare ? sharedUrl : null;
  const formPrefill =
    againPrefill && (!liveShare || againPrefill.receivedAt > liveShare.receivedAt) ? againPrefill : liveShare;

  /** Every "analyze another" / "stop watching": a fresh, empty intake. Terms
   *  stay accepted (they are remembered by the form, not cleared here). */
  const startOver = () => {
    setFromHistory(false);
    setOpenedSaved(false);
    setDismissedShare(sharedUrl);
    setAgainPrefill(null);
    reset();
  };

  /** Expired run: back to the intake with its link in the field, if stored. */
  const analyzeAgain = () => {
    setFromHistory(false);
    setOpenedSaved(false);
    setDismissedShare(sharedUrl);
    setAgainPrefill(againUrl ? { url: againUrl, receivedAt: Date.now() } : null);
    reset();
  };

  /* Refinement 9 (item 7): "Choose the file again" on an expired file run
     opens the file picker itself. It has to happen here, inside the tap: a
     picker opened from a later render (once the intake has mounted) is
     refused by browsers without a live user gesture, and by the Android
     WebView too. So the input lives in this always-mounted shell, the tap
     clicks it synchronously and then returns to the intake, and the chosen
     file is handed to the form, which gives it every check Browse would.
     The terms gate still applies, read from storage at tap time: unticked,
     no picker, the intake shows the terms error (as Browse does since
     refinement 8). Out of free runs, no picker either: the intake's banner
     and blocked note say why. Cancelling the picker leaves the intake. */
  const filePickerRef = useRef<HTMLInputElement>(null);
  const [handoff, setHandoff] = useState<IntakeHandoff | null>(null);
  const takeHandoff = useCallback(() => setHandoff(null), []);
  const chooseFileAgain = () => {
    if (!freeRuns.blocked) {
      if (readTermsAccepted()) filePickerRef.current?.click();
      else setHandoff({ kind: "terms" });
    }
    startOver();
  };

  /* Refinement 1, #6: each phase of a run (intake → progress → result or
     failed) starts at the top. The view swaps inside the same scroller, so
     without this a result opened from a long intake scroll, or a failure
     shown under a scrolled progress view, began part-way down. Layout effect:
     before paint, so the old offset is never drawn. Both scrollers — the
     section from 32rem up, `.viewport` below it. */
  const runPhase =
    status === "idle" ? "intake" : status === "complete" ? "result" : status === "failed" ? "failed" : "progress";
  const analyzeRef = useRef<HTMLElement>(null);
  const lastPhase = useRef(runPhase);
  useLayoutEffect(() => {
    if (lastPhase.current === runPhase) return;
    lastPhase.current = runPhase;
    const section = analyzeRef.current;
    if (!section) return;
    section.scrollTop = 0;
    const viewport = section.closest(".viewport");
    if (viewport) viewport.scrollTop = 0;
  }, [runPhase]);

  const handleOpenRun = (runId: string, sourceKind?: RunSourceKind | null) => {
    /* Pushes a history entry, so back from a run lands on the list it was
       opened from rather than dropping out of the app. The summary's
       `source_kind`, when it has one, seeds the run's frames before the
       first status response arrives. */
    goToMainTab("analyze", { push: true });
    setFromHistory(true);
    setOpenedSaved(false);
    void openRun(runId, sourceKind);
  };

  /* A run saved to the account. The detail is fetched first, from History,
     so a failure stays there with its reason; once it is on screen (or the
     unavailable view is), the same push to Analyze as above. */
  const handleOpenSaved = async (summary: SavedRunSummary) => {
    const outcome = await openSavedRun(summary);
    if (outcome.kind === "shown" || outcome.kind === "gone") {
      goToMainTab("analyze", { push: true });
      setFromHistory(true);
      setOpenedSaved(outcome.kind === "shown");
    }
    return outcome;
  };

  /* The account's list is re-read when History opens and after a run of
     this session finishes (the server has just saved it). */
  useEffect(() => {
    if (activeTab === "history") void refreshSavedHistory();
  }, [activeTab]);
  useEffect(() => {
    if (status === "complete" && !fromHistory && savingRuns) void refreshSavedHistory();
  }, [status, fromHistory, savingRuns]);

  /* UX fix spec 4.5: a run opened from History offers the way back to it.
     True only from `handleOpenRun`; every reset and every new submit clears
     it. */
  const backToHistory = () => goToMainTab("history");
  const submitFresh: typeof submit = (...args) => {
    setFromHistory(false);
    setOpenedSaved(false);
    return submit(...args);
  };

  /* UX fix spec 4.6: the tab title names the view and the run state. */
  const titleLabel =
    activeTab === "analyze"
      ? status === "idle"
        ? "Analyze a video"
        : status === "complete"
          ? result?.title?.trim() || "Result"
          : status === "failed"
            ? expired
              ? expiredReason === "saved"
                ? "Run unavailable"
                : "Run expired"
              : "Run failed"
            : "Analyzing"
      : activeTab === "history"
        ? "History"
        : activeTab === "api-key"
          ? "Gemini key"
          : activeTab === "releases"
            ? "Releases"
            : activeTab === "account"
              ? "Account"
              : null;
  useDocumentTitle(titleLabel);

  /* No `data-frame` here any more. Phase 2 retired the inner results pane:
     the whole Analyze band is the one scroller (from 32rem up it scrolls
     between the fixed nav and footer; below, `.viewport` scrolls under the
     sticky nav and footer/dock) — see app-shell-layout.md. `fixed` survives
     only on the standalone routes that still opt into it. */
  return (
    <div className="shell" data-view={activeTab}>
      <AppNav
        activeTab={activeTab}
        onSelectTab={goToMainTab}
        showAccount={showAccount}
        accountState={accountState}
        accountInitial={accountInitial}
      />

      {activeTab === "analyze" && (
        <main ref={analyzeRef} className="view-scroll" data-view="analyze" aria-label="Analyze">
          {status === "idle" && (
            <div className="intake-layout">
              {/* Always in the DOM, empty and zero-height when the deployment
                  is healthy, so the polite live region exists *before* the
                  report lands and can announce it. A conditionally-rendered
                  live region announces nothing, and a permanently visible
                  "all systems operational" strip is chrome that tells the
                  user nothing they can act on. A grid item of its own above
                  the centred intake, read before the controls it describes. */}
              <div className="cap-slot" aria-live="polite">
                {reachability !== "ok" ? (
                  <ReachabilityNotice state={reachability} />
                ) : (
                  notice && <CapabilityNotice report={notice} />
                )}
              </div>
              <div className="intake">
                {/* Free runs (Phase 5b, IntakeFreeApp / IntakeLimitApp), above
                    the title on every shell. The wrapper is always in the DOM
                    so the polite status region exists before the count lands
                    and can announce it (and the switch to "used"); empty and
                    zero-height when a key is saved, the deployment has no
                    limit, or the allowance could not be read.
                    Until the first read answers (2026-11-14, Android QA run
                    22) it holds an invisible, inert stand-in strip with the
                    commonest sentence, so the real one lands in space already
                    taken at every width instead of pushing the page down. */}
                {/* Desktop (60rem up, 2026-11-14 owner): the allowance sits at
                    the right end of the title's row, sized to its words; the
                    title row's height is the title's, so the card does not
                    move when the count lands. Phones keep the strip stacked
                    above the title (DOM order: status first). */}
                <div className="intake-head">
                  <div className="free-runs-slot" role="status" data-pending={freeRuns.pending || undefined}>
                    {freeRuns.banner && stripKnown ? (
                      <FreeRunsBanner
                        banner={freeRuns.banner}
                        offerSignIn={showAccount && authUser.ready && !authUser.user}
                        offerUpgrade={billing !== null && billing.plan === "free"}
                        extraRunPrice={extraRunPrice}
                      />
                    ) : freeRuns.pending || freeRuns.banner ? (
                      <div className="free-runs-ghost" aria-hidden="true" inert>
                        <FreeRunsBanner banner={FREE_RUNS_GHOST} offerSignIn />
                      </div>
                    ) : null}
                  </div>
                  <h1 className="intake-title">New analysis</h1>
                </div>
                <UploadForm
                  onSubmit={submitFresh}
                  submitting={submitting}
                  blocked={freeRuns.blocked && stripKnown}
                  blockedPeriod={freeRuns.banner?.period}
                  /* The out-of-runs offer, in order: sign in, upgrade, key. */
                  blockedOffer={
                    showAccount && authUser.ready && !authUser.user
                      ? "sign-in"
                      : billing !== null && billing.plan === "free"
                        ? "upgrade"
                        : "key"
                  }
                  sharedUrl={formPrefill}
                  urlCapability={urlDownload}
                  /* Back at idle with an error means the submit was rejected,
                     the server could not be reached, or a history row would
                     not open. The control that failed is still on screen with
                     whatever the user typed, so pressing it again is the whole
                     recovery: a compact notice at the top of the card, not
                     the progress view's notice card with its own actions. */
                  submitError={error}
                  handoff={handoff}
                  onHandoffTaken={takeHandoff}
                  limits={mediaLimits.limits}
                  signInForMinutes={signInForMinutes}
                />
                {/* Paid saved history (2026-11-14): for an account that saves
                    its runs the result is kept on the account, not for an hour. */}
                <p className="intake-retention">
                  {savingRuns
                    ? "Your video is deleted from our servers when the run finishes. The result is saved to your account until you delete it."
                    : "Your video is deleted from our servers when the run finishes. The result is kept for up to an hour, then deleted."}
                </p>
              </div>
            </div>
          )}

          {(status === "queued" || status === "processing" || status === "failed") && (
            <div className="run-state">
              <RunStatusView
                status={status}
                stage={stage}
                sourceKind={sourceKind}
                error={error}
                connectionLost={connectionLost}
                lostCause={lostCause}
                sourceLabel={sourceName ?? sourceMetadata?.source_url.replace(/^https?:\/\/(www\.)?/i, "") ?? null}
                retryInSeconds={reconnectIn}
                retrying={reconnecting}
                reconnectAttempt={reconnectAttempt}
                retryBusy={submitting}
                onReset={startOver}
                onRetry={canRetry ? retry : undefined}
                onRetryNow={reconnectNow}
                expired={expired}
                expiredReason={expiredReason}
                canRefill={againUrl !== null}
                onAnalyzeAgain={sourceKind === "file" && againUrl === null ? chooseFileAgain : analyzeAgain}
                onBackToHistory={fromHistory ? backToHistory : undefined}
                mediaKind={mediaKind}
                freeRunRefunded={freeRunRefunded}
              />
            </div>
          )}

          {status === "complete" && result && (
            <div className="results-layout">
              <div className="source-col">
                <p className="section-label">Source</p>
                {/* On a phone the source collapses behind this one-line pill
                    (ResultsMobile.png), so the results are the first thing on
                    screen. From 56rem the column stands beside the results and
                    the pill is display:none — the panel is always open there. */}
                {(sourceMetadata || fileSource) && (
                  <button
                    type="button"
                    className="source-toggle"
                    onClick={() => setSourceOpen((open) => !open)}
                    aria-expanded={sourceOpen}
                    aria-controls="source-panel"
                  >
                    {sourceMetadata?.uploader && (
                      <span className="source-card__monogram" aria-hidden="true">
                        {creatorInitials(sourceMetadata.uploader)}
                      </span>
                    )}
                    <span className="source-toggle__text">
                      {sourceMetadata ? (
                        <>
                          Source: {platformName(sourceMetadata.platform)}
                          {sourceMetadata.uploader ? `, ${sourceMetadata.uploader}` : ""}
                        </>
                      ) : (
                        <>Source: {fileSource?.name ?? "uploaded file"}</>
                      )}
                    </span>
                    <ChevronDown className="source-toggle__chevron" aria-hidden="true" />
                  </button>
                )}
                <div className="source-panel" id="source-panel" data-open={sourceOpen ? "true" : "false"}>
                  {sourceMetadata ? (
                    <SourceCard metadata={sourceMetadata} />
                  ) : fileSource ? (
                    <FileSourceCard name={fileSource.name} durationSeconds={fileSource.durationSeconds} />
                  ) : (
                    <p className="pending-note">
                      No source details for this run — it was an uploaded file.
                    </p>
                  )}
                </div>
                {fromHistory ? (
                  <button type="button" className="btn btn-secondary btn-block reset-wide" onClick={backToHistory}>
                    Back to History
                  </button>
                ) : null}
                <button type="button" className="btn btn-secondary btn-block reset-wide" onClick={startOver}>
                  Analyze another
                </button>
              </div>

              <div className="results-col">
                <p className="section-label">Results</p>
                <article className="result-card">
                  <ResultsView
                    result={result}
                    sourceMetadata={sourceMetadata}
                    completeness={completeness}
                  />
                </article>
                {/* UX fix spec 4.4: where the result is kept. Static text, so
                    it reserves its own height. Shown even when History cannot
                    be saved: that error is only known to the History panel's
                    own read, and a second IndexedDB read here is not cheap. */}
                {/* Saved history (2026-11-14): a run this account saved (just
                    finished while saving, or opened from its saved runs) says
                    so; anything else is this browser's copy, as before. */}
                <p className="result-saved">
                  {(fromHistory ? openedSaved : savingRuns)
                    ? "Saved to your account. Open it from History on any device where you sign in."
                    : `History keeps your last ${HISTORY_LIMIT} runs in this browser. Not synced.`}
                </p>
                {/* The same actions, placed under the card on a phone where
                    the source column is a pill above it. CSS shows exactly
                    one of each pair. */}
                {fromHistory ? (
                  <button type="button" className="btn btn-secondary btn-block reset-narrow" onClick={backToHistory}>
                    Back to History
                  </button>
                ) : null}
                <button type="button" className="btn btn-secondary btn-block reset-narrow" onClick={startOver}>
                  Analyze another
                </button>
              </div>
            </div>
          )}
        </main>
      )}

      {/* Every view below is its own `.view-scroll` band: from 32rem up the
          band itself is the scroller, full-bleed between the fixed nav and
          footer, scrolling only when its content is taller than that band
          (see app-shell-layout.md). Each page carries its own serif header —
          the Terminal-era `.col-label`/`.surface`/`.pane` frame is gone.
          Each band is a `<main>` (refinement 6, A11-02): exactly one view
          renders at a time, so a page has exactly one main landmark. */}
      {activeTab === "history" && (
        <main className="view-scroll" data-view="history" aria-label="History">
          <HistoryPanel
            onOpenRun={handleOpenRun}
            onAnalyze={() => goToMainTab("analyze")}
            saved={savedHistory}
            paid={paid}
            onOpenSaved={handleOpenSaved}
            onOpenAccount={() => goToMainTab("account")}
          />
        </main>
      )}

      {activeTab === "api-key" && (
        <main className="view-scroll" data-view="api-key" aria-label="Gemini key">
          <ApiKeyPanel
            budgetCapability={dailyBudget}
            /* Unlike the intake hint, offered with or without a key saved:
               this page is where the key goes in. */
            signInForMinutes={showAccount && authUser.ready && !authUser.user ? mediaLimits.upgradeMinutes : null}
            signInPending={keySignInPending}
            signInStandInMinutes={mediaLimits.byokMinutes ?? 10}
          />
        </main>
      )}

      {activeTab === "releases" && (
        <main className="view-scroll" data-view="releases" aria-label="Releases">
          <VersionLogPanel />
        </main>
      )}

      {activeTab === "account" && (
        <main className="view-scroll" data-view="account" aria-label="Account">
          <AccountPanel
            authCapability={authCapability}
            runInProgress={runInProgress}
            capabilitiesSettled={capabilitiesSettled}
            freeRuns={freeRuns.banner}
            freeRunsPending={freeRuns.pending}
            billing={billing}
            billingPending={billingPending}
            billingFailed={billingFailed}
            checkoutReturn={checkoutReturn}
            limits={mediaLimits}
            savedHistory={savedHistory.mode}
            savedUntil={savedHistory.status?.expires_at ?? null}
          />
        </main>
      )}

      {/* Both shells' chrome is always rendered; `<html data-shell>` decides
          which shows (footer in a browser tab and a wide installed window,
          dock in a phone-width installed app). */}
      <SiteFooter />
      <BottomTabBar activeTab={activeTab} onSelectTab={goToMainTab} showAccount={showAccount} />

      {/* The expired view's picker (item 7, above). Out of the tab order and
          the accessibility tree: the visible control is the button. */}
      <input
        ref={filePickerRef}
        type="file"
        accept={MEDIA_FILE_ACCEPT}
        className="hidden"
        tabIndex={-1}
        aria-hidden="true"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) setHandoff({ kind: "file", file });
          event.target.value = "";
        }}
      />
    </div>
  );
}

/**
 * The same shell, told which tab it is by the URL.
 *
 * Split out so the `useSearchParams` call sits in exactly one component: it is
 * what suspends during prerender, and putting it in `HomeScreen` itself would
 * make the Suspense fallback suspend too.
 */
export function RoutedHomeScreen() {
  const activeTab = useMainTab();
  return <HomeScreen activeTab={activeTab} />;
}
