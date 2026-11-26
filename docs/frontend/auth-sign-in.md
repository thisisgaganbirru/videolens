# Sign-in and the Account tab (auth phase 2)

Optional sign-in for the web app and the installed app, plus the Account tab
where a signed-in person manages their VideoLens API keys. Plan and phases:
`docs/auth-plan.md`. Backend half: `docs/backend/auth.md`.

Anonymous use stays first-class. With sign-in off (either env var blank) the
app is byte-for-byte the anonymous app: no Account tab, no provider code
loaded, no bearer on any request.

## Configuration

| Variable | Meaning |
|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | The Supabase project URL. Inlined at build time; its origin is added to the CSP `connect-src`. |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | The project's `sb_publishable_…` key. Public by design. |

Blank either one and `buildAuthSession()` returns `NullAuthSession`. Both
are build-time values: changing them needs a rebuild (and a dev server
restart, since `next.config.mjs` computes the CSP header once at start).
In the container build they reach `next build` only because
`frontend/Dockerfile` declares both as `ARG`s; a service variable the
Dockerfile does not declare is ignored and sign-in stays hidden.

## Layers

| Layer | File | Role |
|---|---|---|
| domain | `entities.ts` | `AuthUser`, `AccountResponse` (+ `AccountWorkspace`, `AccountEntitlement`, which gains an optional `complimentary` on 2026-11-14, see `billing.md`), `ApiKeySummary`, `ApiKeyCreated`, `ApiKeyListResponse` |
| domain | `ports.ts` | `AuthSession` (`enabled`, `load`, `user`, `hasSession`, `getToken`, `requestEmailCode`, `verifyEmailCode`, `signOut`, `subscribe`, and since 2026-11-22 `signInWithGoogle`, `googlePending`, `redirectResult`, `dismissRedirectResult`), `AuthRedirectBrowser` (where Google's consent page opens and how its answer comes back: `returnUrl`, `open`, `close`, `takeInitialReturn`, `watch`), `AuthRedirectResult`, `AccountGateway` (`fetchAccount`, `listKeys`, `createKey`, `revokeKey`), `ServerAuthStatus` (the server's `auth` capability: `unknown`/`ok`/`off`), `CallerIdentity` (`lastOwner()`) |
| domain | `entities.ts` (History) | `HistoryRecord.owner`: `user:<id>` or `anonymous`, the identity the run was created or imported under |
| domain | `errors.ts` | `AuthFlowError(reason)`, reasons `invalid_email`, `invalid_code`, `rate_limited`, `unreachable`, `unavailable`, `cancelled` (Google consent refused, 2026-11-22), `unknown` |
| infrastructure | `authSession.ts` | `SupabaseAuthSession` and `NullAuthSession`, `buildAuthSession(browser)`. The only file that names Supabase |
| infrastructure | `authBrowser.ts` | `SystemAuthBrowser` (the `AuthRedirectBrowser`): this tab on the web; `@capacitor/browser` + `@capacitor/app` deep links in the installed app, lazily imported. `NATIVE_RETURN_URL`, `readReturn` |
| infrastructure | `apiClient.ts` | The shared caller transport: `X-Client-ID` always, `X-Device-Token` when held, `Authorization: Bearer` only when signed in **and** the server's `auth` capability is `ok`. Records the identity each request went out as (`lastOwner`) |
| infrastructure | `serverAuthStatus.ts` | `MemoryServerAuthStatus`, fed by `FetchCapabilitiesGateway` from every report's `auth` row (a report without the row counts as `off`) |
| infrastructure | `accountGateway.ts` | `/api/me`, `/api/keys` (GET, POST), `DELETE /api/keys/{id}` |
| infrastructure | `container.ts` | `authBrowser`, `authSession`, `serverAuthStatus`, `apiClient` (also exported as `callerIdentity`), `accountGateway`; `runsGateway` and `freeRunsGateway` now take the `ApiClient` |
| application | `useAuthSession.ts` | `useAuthUser()` (who is signed in, `ready`), `useEmailCodeSignIn()` (the OTP form state), `useGoogleSignIn()` (the Google button), `useGoogleReturnLanding()` (mounted by HomeScreen: a Google answer brings the shell to Account), `signOut()` |
| application | `useAccount.ts` | `/api/me` for the signed-in user: `unavailable` (503), `rejected` (401), `failed` |
| application | `useApiKeys.ts` | list, create, revoke. The one-time secret lives only in `justCreated`; the list gets the summary with `secret` stripped, so "Done" drops it for good |
| application | `useRunHistory.ts` / `historySync.ts` | `useHistoryBoot({ready, userId})` re-imports the server's runs (`importServerRuns`) when a person signs in. `recordSubmitted` and imports stamp `owner`; `recordGone` decides what a 404 means (below) |
| application | `useCapabilities.ts` | exposes the `auth` capability row |
| components | `panels/AccountPanel.tsx` | the tab |

## The provider adapter

- `@supabase/supabase-js` **2.118.0**, pinned exact, loaded with a dynamic
  `import()` the first time anything asks for a token, so a build without
  sign-in never fetches it.
- Client options: `persistSession: true`, `autoRefreshToken: true`,
  `flowType: "pkce"`, `detectSessionInUrl: false` everywhere (since
  2026-11-22; the Google return is read by the adapter itself, below).
- The session lives in this origin's localStorage, which the Android backup
  rules already exclude (`security-headers.md`).
- `hasSession()` is synchronous: a session in memory, or the stored
  `sb-<ref>-auth-token` key (named explicitly as `storageKey`, the library's
  own default), so it answers before the library has loaded.
- `getToken()` waits for the provider at most 4 s (`LOAD_WAIT_MS`). It
  returns `null` only when nobody is signed in. When a session exists but no
  token can be had (load timed out or failed, a stored session the library
  could not recover, a refresh that failed on the network) it **throws**, and
  `ApiClient` turns that into a `NetworkError` ("Your sign-in could not be
  confirmed just now..."). The poll treats it as a lost connection and
  reconnects, instead of asking anonymously and getting a 404 for the
  person's own run.
- `signOut()` also removes the stored key by hand, so a session the library
  cannot load can still be cleared.
- `onAuthStateChange` only records the session and notifies; it never calls
  back into the client (that can deadlock supabase-js's lock).
- Errors are classified structurally (`status`, `code`, `name`) into
  `AuthFlowError`, so nothing above infrastructure knows the provider.
- `signOut()` is `scope: "local"`: this device only.

## When the bearer is sent

The backend reads a bearer *instead of* `X-Client-ID`, so a bearer sent to a
server without a matching verifier would make every caller route answer
401/503. `ApiClient` therefore sends it only when all hold: sign-in is
configured, a session exists, and `ServerAuthStatus` says the server's `auth`
capability is `ok`. While the capability report is still in flight a
signed-in request waits for it, at most 4 s; still unknown after that, the
request goes out anonymous. Anonymous is also what a server reporting `auth`
as anything but `ok` gets, so the app keeps working there with a leftover
session.

## Emailed code

- `signInWithOtp({ email, options: { shouldCreateUser: true } })`, then
  `verifyOtp({ email, token, type: "email" })`.
- The code is **exactly 6 digits** (owner, 2026-11-22; it accepted 6 to 8
  while `videolens-dev` sent 8). `CODE_LENGTH = 6` in `useAuthSession.ts`;
  the field keeps `inputmode="numeric"` and `autocomplete="one-time-code"`,
  has `maxLength={6}` and placeholder `123456`. Typed or pasted text is
  reduced to digits and cut to six (`cleanCode`); the field's own `onPaste`
  does this before `maxLength` could truncate a paste such as
  "Your code: 123456". Verify with anything but six digits says "Enter the
  6-digit code from the email." **Dashboard dependency:** every Supabase
  project must send 6 (Authentication, Email, "Email OTP Length"); a project
  left at 8 fails at Verify.
- Copy says the code expires in 10 minutes (the project's 600 s setting).
- Resend is offered after 60 s (Supabase refuses a second code sooner), with
  a visible countdown. "Use a different email" goes back to step one.
- Google sits above it since 2026-11-22 (next section).

## Google sign-in (auth phase 4, 2026-11-22)

"Continue with Google" is the first control on the signed-out card, a
neutral outlined pill (`.btn-secondary` on the card's white, so the
four-colour mark sits on a neutral ground in both themes, as Google's
branding asks) with the official "G" inline as SVG, then the intake's
`.divider` "or", then the email form. While a run is in progress it is held
with the same `RUN_GUARD` note as Verify (`aria-disabled` plus a handler
guard). A start failure or a refused or failed return shows as
`role="alert"` under it; "Finish signing in on Google's page." is a polite
status while the app's browser is open.

**Card layout (owner's reference, 2026-11-22).** Under the title and the
"No password needed" line, one column (`.acct-sign-in-stack`), every
control full width at 3rem: "Continue with Google" (outlined, quieter),
an uppercase centred "OR" (`.divider.acct-or`), the email field
(placeholder "Enter your email"; the "Email" label is `sr-only`, and the old
help line "We'll email you a 6-digit code. New here?…" is now its
`sr-only` description), then the filled primary "Continue with email",
which is the old Send code (same `flow.send()`; "Sending…" while busy, the
status line moved to `sr-only`). Under it a centred muted note
(`.acct-consent`): "By continuing, you agree to VideoLens's Terms and
acknowledge the Privacy Policy." with `.text-link`s to `/terms` and
`/privacy`. No marketing-consent clause: VideoLens sends no promotional
email, and implied consent would not be a valid opt-in. The code step that
follows is unchanged. Verified light and dark, and at 301px control width
(phone card content), by screenshot on the dev server.

**One return path for web and app.** `detectSessionInUrl` is off; the
adapter reads the answer itself (`finishReturn`), because supabase-js leaves
a refusal's `?error=` in the address bar and never reports it to a screen,
leaves `?code=` behind after a failed exchange, and strips the URL with a
`replaceState` Next does not see.

1. `signInWithGoogle()`: a settings preflight (`GET <supabase>/auth/v1/settings`,
   4 s) refuses early with `unavailable` when `external.google` is false (the
   consent address would otherwise be a bare JSON error page with no way
   back) and `unreachable` when the read cannot be made at all. Then
   `signInWithOAuth({ provider: "google", options: { redirectTo:
   browser.returnUrl(), skipBrowserRedirect: true, queryParams: { prompt:
   "select_account" } } })` builds the address and stores the PKCE verifier
   (`sb-<ref>-auth-token-code-verifier`). A marker
   `videolens-google-signin-pending` (a timestamp) goes into localStorage,
   and `browser.open(url)` leaves.
2. The answer reaches `finishReturn(raw)`: it closes the app browser,
   **synchronously takes the marker** (missing or older than 30 min: the
   link is ignored, so a reload, a bookmark or a link heard twice at cold
   start never exchanges twice), then either publishes the error
   (`access_denied` is `cancelled`; provider or signup disabled is
   `unavailable`; rate limits `rate_limited`; else `unknown`) or calls
   `exchangeCodeForSession(code)`. The outcome is `redirectResult()`
   (`{id, ok}` or `{id, ok: false, error}`), and listeners are notified.
3. `useGoogleSignIn` dismisses an ok result (the panel turns signed in on its
   own) and keeps a failure on screen; `useGoogleReturnLanding` (HomeScreen)
   routes to Account once per result id.

**Web.** Return address `${location.origin}/app?view=account`. The page
loads; `load()` calls `takeInitialReturn()`, which (on `/app` with
`view=account` and any of `code`, `error`, `error_code`, `error_description`)
strips those and `sb_flow_id` with a `replaceState` that keeps Next's history
state shape, and hands the URL over before `load()` settles, so the panel
goes from "Loading…" straight to signed in. Coming back from Google's page
with the browser's back button (bfcache `pageshow`) clears the pending state.
No CSP change: the consent page is a top-level navigation (not covered by
`connect-src` or `form-action`), and the settings read and code exchange go
to the Supabase origin `connect-src` already allows.

**Android.** Return address `ai.videolens.app://auth/callback`.
`SystemAuthBrowser` lazily imports `@capacitor/browser` (**8.0.5**, exact)
and `@capacitor/app`, opens the consent page in a Custom Tab, and listens
for `appUrlOpen` (warm) plus `App.getLaunchUrl()` (cold start); both filter
on that scheme, host and path. `browserFinished` (the person closed the tab)
clears the waiting state. `AndroidManifest.xml` has an intent filter on
`MainActivity` (VIEW, DEFAULT, BROWSABLE, scheme `ai.videolens.app`, host
`auth`, path `/callback`); `launchMode="singleTask"` delivers the link to the
running activity. The PKCE verifier and the marker live in the WebView's
Local Storage, which the backup rules already exclude, so they are
unchanged. `npx cap update android` registered the plugin in the two tracked
Gradle files (`capacitor.settings.gradle`, `app/capacitor.build.gradle`).
On the web every native call is skipped and the plugins are never loaded.

**Android build configuration.** The APK is a static export, so the two
`NEXT_PUBLIC_SUPABASE_*` values must be in the environment of the
`npm run android:sync` step that builds it; there is no runtime config. CI
passes them per lane as the `supabase_url` / `supabase_publishable_key`
inputs of `reusable-android-checks.yml` (production project
`lslepkhscayqxmsnckns`, dev project `pjekwwiaocywdbwqgtgl`, publishable keys
only) and fails the release and dev-artifact builds when either is missing
or did not reach the export JS and CSP (`docs/container-workflows.md`, "The
APK's build-time configuration"). Up to v2.3.0-build543 CI passed neither,
so every CI-built APK had `auth.enabled` false and no Account tab while local
builds (reading `.env.local`) looked fine. When QA'ing sign-in on a device,
use a CI APK, not only a local one. Both the production and the `.dev` APK
register the same `ai.videolens.app://auth/callback` scheme; with both
installed, Android may ask which app opens the Google return. Each Supabase
project's Redirect URLs must list that address (dashboard, below).

**Identity.** Supabase links a Google sign-in to an existing user with the
same verified email, so the `user:<id>` owner, server-side runs, saved
history and the sign-out-hides-runs behaviour are identical to an emailed
code. Nothing in History, `ApiClient` or ownership knows how a session was
made.

**Dashboard requirements (not in code).**
- Supabase, Authentication, Providers, Google: enabled with the Google
  client id and secret.
- Supabase, Authentication, URL Configuration, Redirect URLs: each web
  origin **with a wildcard path** (`http://localhost:3005/**`,
  `https://<dev frontend>/**`, `https://<prod frontend>/**`); an exact
  origin does not match `/app?view=account`. Plus
  `ai.videolens.app://auth/callback`. A return address not on the list makes
  Supabase fall back to the Site URL.
- Google Cloud OAuth client (Web application): authorized redirect URI
  `https://<project-ref>.supabase.co/auth/v1/callback`.

## The Account tab

- **Shown** only when `authSession.enabled` *and* the server's `auth`
  capability is `ok`. Computed in `HomeScreen` and passed to `AppNav`,
  `BottomTabBar` and `MoreSheet` (`navTabs(showAccount)`).
- **Top bar entry (2026-11-13).** From 48rem the web top bar draws Account
  not as a text tab but as a round 44px link at the far right, after the
  theme toggle (`.nav-account` in `AppNav`): lucide `UserRound` signed out
  (superseded 2026-11-14 by the "Sign in" pill, below),
  the email's first character uppercased signed in (`accountInitial`,
  computed in `HomeScreen` from `authUser.user.email`; null falls back to
  the glyph). `aria-label` and `title` "Account", same href and in-place
  switch as the old tab, `aria-current="page"` plus the text tabs' filled
  ink when current. It is shown exactly where `.nav-links` is (unlayered
  48rem rule, hidden again in the sideways app shell). The web phone menu
  and the More sheet keep Account as a text row; the dock is unchanged.
  `UserRound` rather than the More sheet's `CircleUserRound` because the
  button's own round frame already draws the circle.
- **Dock entry (2026-11-14).** In the installed app's phone dock
  (`BottomTabBar`, app shell at ≤ 37.5rem wide or ≤ 31.25rem tall) Account is
  a fourth item: Analyze / History / Account / More, under the same
  `showAccount` gate; with sign-in off the dock stays three items. Lucide
  `CircleUserRound` plus the label "Account", the same stroke family as
  `CircleDot` and `Clock`; no email initial, because a 20px letter reads as
  an avatar badge rather than a dock glyph. `aria-current="page"` on
  `?view=account`, same in-place switch as the other dock tabs. The More
  sheet no longer has an Account row at all: the sheet is only reachable from
  the dock, so whenever the row could show, the dock item shows too. On a
  leftover session with sign-in unavailable, `?view=account` lights no dock
  item (before, More lit with no matching row). Routes that do not pass
  `showAccount` (landing, Privacy, Terms, 404, offline) keep a three-item
  dock, as their More sheet had no Account row before either. The top-bar
  round button stays ≥ 48rem only; the web phone menu keeps its text row.
- **Sign in call to action (2026-11-14).** Owner: the bare person glyph did
  not say what it did. From 48rem, signed out, the top bar's Account control
  is a labelled pill "Sign in" (`.nav-account.nav-account--signin`: secondary
  button voice, ink hairline on transparent, 15px/600, 44px tall, same href
  and in-place switch, filled ink with `aria-current` on `?view=account`).
  Not green: the view's own primary (Analyze link, Download .md) keeps the one
  green fill. Signed in, the round initial button is unchanged (a signed-in
  user with no email gets the `UserRound` glyph). While the session loads
  (`authUser.ready` false) the bar draws neither, so the right-aligned row
  never jumps from pill to circle. `HomeScreen` passes
  `accountState: "loading" | "signed-out" | "signed-in"` to `AppNav`. The web
  phone menu's Account row reads "Sign in" while signed out ("Account"
  loading or signed in). The dock item stays "Account" (owner-approved
  4-item dock). With auth off
  nothing renders, as before.
- **Every route (2026-11-14, follow-up).** Landing, Privacy, Terms and 404
  render the same entry: `RouteNav` / `RouteTabBar` (client wrappers around
  `AppNav` / `BottomTabBar`) call `useAccountEntry()` in
  `application/useAccountEntry.ts`, which applies the same gate (provider
  configured *and* `auth` capability `ok`) and the same state
  (`accountEntryFrom`, also used by HomeScreen on `/app`). The `auth` row is
  read once per page load through a module-level promise shared by nav and
  dock (one `/api/capabilities` request); a failed read hides the entry and
  is retried on a later mount. Prerendered and first client render show no
  entry, so no hydration mismatch; it appears once both reads answer. Links
  go to `/app?view=account`. Landing's "Start analyzing" CTAs are unchanged.
  Offline (`/offline`) keeps plain `AppNav`: it is served with no network,
  so the capability can never be read and the entry could never show. The
  Routes-without-`showAccount` note in the Dock entry bullet above is
  superseded: those routes now get the 4-item dock too.
- **Landing label (2026-11-14, follow-up; superseded twice, see the next
  bullet).** On `/` the signed-out entry
  reads "Get started" (bar pill and phone-menu row), because the landing is
  for new visitors and "Sign in" reads as existing users only. It is a prop,
  `signedOutLabel` on `AppNav` (passed through `RouteNav`), default "Sign in";
  `/app`, Privacy, Terms and 404 keep the default. Same href
  (`/app?view=account`) and the same outlined secondary style, not green: the
  hero's filled green "Start analyzing" is on screen at the same time and a
  view gets one green fill. The dock keeps "Account". The signed-out sign-in
  card now welcomes new people: heading (and form label) "Sign in or create
  an account", help line "New here? Verifying your first code sets it up."
- **Landing label, final (2026-11-14, landing refinement).** Signed out, `/`
  passes `signedOutLabel="Get 10 free runs"` (the number is
  `ACCOUNT_FREE_RUNS_PER_MONTH`, moved to the plain module
  `application/accountAllowance.ts` so the server-component landing can read
  it) and `signedOutShortLabel="Sign up free"`. "Get started" sounded like
  "Start analyzing" but went elsewhere (codex reverted it to "Sign in"); this
  label names the account action by its benefit. Outlined secondary voice,
  unchanged. The bar pill renders both labels as spans and CSS shows "Sign up
  free" only from 48rem to 49.99rem: measured at 768px the long label (148px)
  put the bar's right edge 13px into the page gutter; from 784px it fits
  exactly, 800px and up has room. The phone-menu row always reads "Get 10
  free runs" (full-width row). Phones also get a visible entry without opening
  the menu: the inline "Sign in" in the hero's allowance line (see
  `landing-page.md`). `/app`, Privacy, Terms and 404 keep "Sign in".
- **Signed-out lede (2026-11-14).** "Sign in for 10 free runs a day,
  videos up to N minutes with your own key, and API keys for your scripts.
  An account is optional." The 10 is `ACCOUNT_FREE_RUNS_PER_DAY` (from
  `application/accountAllowance.ts`; "a month" until the daily allowance,
  later on 2026-11-14); N is `useMediaLimits().upgradeMinutes`
  passed as the panel's `signInMinutes` prop. When that is null (limits not
  read, or no larger tier) the video clause is left out rather than promised.
- The panel uses the **same gate** for its sign-in form: capability still
  loading, failed to load, or not `ok` all show the calm "Sign-in is not
  available on this server" card and no form. The same card shows when
  `/api/me` answers 503.
- `/app?view=account` always renders the panel. In the unavailable state a
  leftover session still gets a "Signed in as" card with **Sign out**, so a
  device signed in on a server that later lost sign-in can always sign out
  there, even with the tab hidden.
- **Signed out:** the optional lede, email, Send code, then the code step
  (Verify, resend, change email).
- **Signed in:** the grouped-list layout (option A, 2026-11-09); see
  "Account layout: option A, grouped list" below.
- **API keys row:** a native disclosure. Opening it the first time sets
  `visited`, which enables `useApiKeys` and loads the keys; nothing is
  fetched before that. The body stays mounted when collapsed, so a freshly
  created secret is kept. It resets on leaving the page, signing out, or
  changing users. Inside: create, Copy/Done for the one-time secret, and the
  list with inline revoke confirmation.
- **Free runs line (2026-11-13).** The identity card's meta line reads
  "Free runs left today: N of 10" when the server counts the account's
  allowance (`scope: "account"`; daily since 2026-11-14, worded from
  `period`, so a `month` period would read "this month"), and keeps "Free runs left on this
  device: N" otherwise (including an older server that sends no scope). The
  panel takes the `FreeRunsBanner` object from HomeScreen's one `useFreeRuns`
  (prop `freeRuns`, was `freeRunsLeft`), and HomeScreen re-reads the
  allowance on every sign-in and sign-out. See `free-runs.md`, "Account
  allowance".
- **On this device / Help:** plain link rows (History, Your Gemini key;
  Privacy policy, Terms of use, What's new). They show in every state:
  signed out, unavailable, deleted and signed in.
- Tab links use `mainTabHref` and `goToMainTab` for plain clicks, following
  existing web/native navigation; modified clicks keep normal link behavior.
- **Run ownership across identities.** The server holds a run for the
  identity that created it. Each History record stores that identity
  (`owner`). On a 404, `recordGone` compares it with the identity the 404
  was asked under (`callerIdentity.lastOwner()`):
  - different: `other-owner`. Nothing is written, the screen shows
    `OTHER_OWNER_MESSAGE` ("started under a different sign-in... switch back
    to see it"), and the History row keeps its status. This covers "Analyze
    another" or stop watching then switching identity, a reload whose
    startup reconcile meets the 404, signing out then reloading, and signing
    in from another tab.
  - same, or the record has no owner (written before auth): the old rule,
    expired, written to History.
- **Run guard (on screen):** Verify, Sign out and Sign out everywhere are also held, with a note,
  while the run on Analyze is submitting, queued or processing
  (`runInProgress`), so the watched run is not interrupted at all.
  Since 2026-11-21 `runInProgress` is `useAnalysisRun().holdsSignIn`: a
  submit on its way, or a run the server has answered for that is queued or
  processing with no error. A run stalled on the connection-lost screen,
  reconnecting, or being reopened from History no longer holds it (it once
  left Sign out greyed, `mem/20261121-signout-not-clickable.md`). The note
  (`RUN_GUARD`) shows under the control whenever the guard holds it; it now
  reads "A run is in progress on Analyze. Wait until it finishes: signing in
  or out now would stop this screen following it."
  Since 2026-11-22 the hold also needs a **recent** answer: each server
  answer for the run keeps it for 15 s (`HOLD_FRESH_MS`, five polls). The
  poll keeps running whichever view is showing (HomeScreen is never
  unmounted by a tab switch), so on Account the control frees itself within
  one poll of the run settling; and if the screen stops hearing from the
  server for any reason (a poll stuck before its request, a frozen
  background tab), the hold lapses on its own instead of greying Sign out
  for good. See run-analysis-hook.md.
- Busy controls use `aria-disabled` and handler guards, never `disabled`,
  so focus is not lost (the app-wide rule).

## Account presentation refinement (2026-11-08)

The Account panel keeps the existing editorial theme: Newsreader headings,
Hanken Grotesk controls, paper/surface colors, green accent, card radii and
pill buttons. Presentation changes are limited to `AccountPanel.tsx` and
selectors beneath `.acct-page` in `globals.css`; shared styles and tokens
are unchanged.

- A shorter introduction explains optional sign-in and local History.
- On wide screens the identity details and Sign out share a row; narrow
  screens keep the stacked layout. Long emails can wrap.
- A hairline separates API-key creation from the explanatory text. The
  create control stacks below the input at widths up to 30rem, and key
  metadata wraps independently.
- The empty key list explains the next action, above a hairline. The
  Phase 3 delete card has a transparent background (the page paper shows
  through) so it stays visually secondary.
- Email and code forms have explicit serif headings and separate explanatory
  text from field labels. While sending or verifying, relevant inputs are
  read-only (still focusable), live status text describes progress, and the
  secondary links expose their existing busy guards with `aria-disabled`.
- The overview uses concise setting rows with chevrons, existing card shapes
  and tokens, native disclosure semantics and explicit focus styles. The
  first Codex pass added an active-key count; the second removed it, and
  the panel shows no count now.
- Deletion copy describes local data retention without claiming the Gemini
  key never leaves the device.

Authentication, requests and deletion behavior are unchanged. Phase 3 is
still unfinished; these presentation edits do not validate its behavior.
Browser visual QA (main session, 2026-11-09, Chrome at 1536 px, signed in
against the local backend): signed-in overview, the three disclosures
opened, the empty key list, the delete confirmation form (opened and
cancelled, not submitted) all render correctly in both themes; no console
errors. Not verified: phone width (the Chrome window would not resize and
`frame-ancestors 'none'` blocks an iframe or popup), the signed-out form,
and the API keys list with keys in it. Phone width is checked on the
bundled Android APK, as always.
The compact overview passed TypeScript, targeted component ESLint, and a
mocked React server-render check for signed-in, signed-out, account-unavailable
and auth-unavailable states. The render check verifies resource links, no
duplicate resource groups, and no key-hook mount while initially collapsed;
it does not exercise browser disclosure interaction or real authentication.

## Phase 3 state and remaining work (2026-11-09)

Phase 3 on the frontend is **in the working tree, uncommitted**: the
`deleteAccount()` port and adapter method, `useAccountDeletion`
(`useAccount.ts`), `DeleteAccountSection` and `DeletedCard` in
`AccountPanel.tsx`, the `.acct-delete-*` styles, and the deletion sentence
on `/privacy`. Codex's presentation pass (section above) landed on top of
those edits in the same files, so the two cannot be committed separately.
Done (frontend agent, 2026-11-09):

- **Code hygiene.** Removed the unused `.acct-page .acct-section-head` rule
  and its `+ .key-help` sibling and the tooling comment from `globals.css`.
  `.acct-delete-list` now shows disc markers (`--color-muted`), the same
  way `.key-steps` restores the markers Tailwind's preflight strips.
  Reverted `frontend/next-env.d.ts`. The rest of the account code checks
  out: every `.acct-*` class in `globals.css` is used. `acct-sign-in` and
  `acct-revoke` are hook classes with no CSS, which is harmless.
  `AccountResources` renders once per state, because the outer render
  covers deleted / unavailable / signed out, and `SignedIn` either returns
  early or renders it once. The deletion hook matches the contract: 204
  succeeds, 401 is `rejected`, 503 is `unavailable`, and
  403/404/405/other are `failed`.
- **Review fix: sign-out race and 401 copy.** `useAccountDeletion` used to
  call `onDeleted()` and only then await `signOut()`. supabase-js clears the
  stored session only after its `/logout` request returns, so pressing "Back
  to sign in" during that wait mounted the signed-in view on the old token,
  and `GET /api/me` re-created the account. Now the hook starts `signOut()`
  and passes the settling promise to `onDeleted(signedOut)`. The panel shows
  `DeletedCard` at once in a `"signing-out"` state: "Back to sign in" is
  `aria-disabled` with a click guard, and a `role="status"` line reads
  "Finishing sign-out on this device…". When the promise settles the state
  becomes `"done"` and the button works. The backend is being changed so that a
  deleted user's token gets 401, so both layers hold. A 401 from `DELETE
  /api/me` can now also mean the account is already gone (a retry whose
  204 was lost), so the `rejected` message no longer says "nothing was
  deleted". It now reads: "This server did not accept your sign-in. If you
  already deleted your account, it is gone. If not, sign out, sign in again
  and try once more." Checks rerun: tsc clean, build and build:mobile pass,
  lint 5 known findings only.
- **Privacy deletion sentence corrected (owner-approved wording).** The
  `/privacy` "Signing in" sentence now says deletion *immediately* removes
  the account record, workspace, API keys, held runs and the provider
  sign-in, and that copies of the email can remain up to about 7 days in
  the provider's daily database backups and sign-in logs, and the hosting
  provider keeps server logs for at least 7 days until they expire. The
  earlier text implied nothing remained. The "Effective" date on the page is
  not a "last updated" date and was left as is (same call as Phase 5a).
- **Checks on this tree.** `tsc --noEmit` is clean. `npm run build` and
  `npm run build:mobile` pass (7 static routes, CSP injected, `sw.js`
  written). `npm run lint` shows only the 5 known findings (4 errors, 1
  warning). The build ran alongside the dev server on 3005 without
  conflict.

Still to do before this ships, in order:

1. **Backend half** (`DELETE /api/me`, migration `0002_auth_user_deleter`,
   `database` probe) is also partial and uncommitted; the UI's `rejected`
   / `unavailable` / `failed` branches cannot be exercised until it is
   finished and the migration is applied on `videolens-dev`. The UI treats a
   404/405 from a server without the route as `failed`, so it is safe
   against the current backend.
2. **Behaviour QA** once the backend exists: delete the account on the
   local in-memory backend (the Supabase user row is the only durable thing
   removed), confirm the `DeletedCard`, sign back in; create, copy and
   revoke an API key through the collapsed `Manage API keys` disclosure.
3. **Review, commit, push** (plain messages). No PR into `dev` until the
   owner asks.
4. **Phone width** on the bundled APK; signed-out form after a deliberate
   sign-out by the owner.

## Account layout: option A, grouped list (2026-11-09)

The owner picked option A of the layout proposal (`mem/20261109-auth-phase3-frontend.md`).
Theme unchanged: existing tokens, Newsreader/Hanken, `.key-card`, no new
colours, fonts or radii. Signed in, top to bottom:

1. Title and lede (unchanged).
2. **Identity card** (`aria-label="Signed in as"`, no heading): email, then
   "Email sign-in · Free runs left on this device: N", then Sign out. N is
   `useFreeRuns().banner.remaining`, passed from `HomeScreen` as
   `freeRunsLeft`; when the banner is null (count unknown, the deployment has
   no limit, or a Gemini key is saved) the free-runs part is left out. The
   run guard note comes *after* the button, so on a phone the email and Sign
   out are never split (on wide screens it spans the grid's second row).
3. **"Your account"** group: one card with the **API keys** row ("Let your
   scripts and agents use VideoLens as you"), a disclosure with a down
   chevron that turns 180° when open. The row shows "N keys" (active keys)
   only after the lazy fetch has answered and N > 0; there is no eager
   fetch. If a one-time secret is still unseen and the row is collapsed, the
   row shows "New key to copy" in accent-strong. `useApiKeys` moved up from
   `ApiKeysSection` into `ApiKeyManager` (`useApiKeys(enabled && visited)`)
   to make that possible.
4. **"On this device"** group: History ("View or remove saved analyses") and
   **Your Gemini key** ("Your own Google key for analyses. Stays in this
   browser."), right-chevron link rows to the existing tabs. Signed in, a
   muted note below: "Both stay in this browser when you sign out."
5. **"Help"** group: Privacy policy, Terms of use, What's new.
6. **End zone**, last: "Sign out everywhere" (ink, underlined text control)
   with its helper text, then "Delete account…" as a muted underlined link.
   The link opens the existing typed-email form in a card (behaviour, run
   guard `RUN_GUARD_DELETE`, focus in and out, and `DeletedCard` unchanged).
   Delete is always the last item.

Heading outline: h1 Account → h2 per group (styled with History's
`.history-group-label`) → a visually hidden h2 "Sign out everywhere or
delete your account" over the end zone → h3 "Delete account" when the form
is open → h4 for its two lists. Rows are at least 56px (`min-height:
3.5rem`), the text controls 44px. The grouped card clips its corners, so row
focus rings are inset (`outline-offset: -2px`).

Removed as dead: `.acct-settings-link`, `.acct-resource-note` and the old
disclosure-toggle padding rules. The "Manage API keys", "Data on this
device" and "Help & privacy" disclosures are gone.

### Sign out everywhere

- Port: `AuthSession.signOutEverywhere()` (`domain/ports.ts`). The null
  adapter is a no-op. Hook: `useSignOutEverywhere()` in `useAuthSession.ts`
  (`idle | working | failed`, `error`, `run`); the panel never calls the
  adapter.
- **The Supabase adapter does not use `scope: "global"`.** In supabase-js
  2.118, `_signOut` removes the local session even when the global logout
  request fails, which would break "on failure, stay signed in". The
  adapter calls `signOut({ scope: "others" })` first (on error nothing local
  is touched, and it throws a classified `AuthFlowError`), then the ordinary
  local `signOut()`. On success the net effect is the same as global. Edge
  case: if the connection drops between the two steps, this device is still
  signed out locally, but its own refresh token may stay valid on the server
  until it expires.
- Failure: an inline `error-inline` alert, and the person stays signed in.
  Success: the session listeners fire and the panel shows the signed-out
  view, as after Sign out. Single click, no confirm (signing in undoes it).
- **Caveat in the copy:** the API verifies Supabase JWTs by JWKS only, so
  another device's current access token keeps working until it expires.
  The project docs record no custom JWT expiry, so the copy says "up to an
  hour" (Supabase's default is 3600 s). VideoLens API keys are not revoked.
  Helper text: "Signs you out on every device. Others may stay signed in for
  up to an hour. API keys keep working until you revoke them."

Files: `components/panels/AccountPanel.tsx`, `components/HomeScreen.tsx`
(`freeRunsLeft` prop), `app/globals.css` (`.acct-page` grouped-list block),
`domain/ports.ts`, `infrastructure/authSession.ts`,
`application/useAuthSession.ts`.

Checks: `tsc --noEmit` clean, `build` and `build:mobile` pass, lint shows
only the 5 known findings. Chrome at 1536 px, signed in against the local
dev server (read-only): identity line with free runs, the group outline,
56px rows, 44px end controls, no horizontal scroll, no console errors. The
API keys disclosure was opened (the list loads) but nothing was created or
revoked, and neither sign-out control nor delete was used. Phone width and
the installed-app shell were not checked in a browser (the Chrome window
cannot be resized); check them on the bundled APK.

## Account refinement (2026-11-14, owner's six items)

Supersedes the wording and order above wherever they differ. Same editorial
system, single column, shared chrome; no new tokens.

**Order, signed in:** identity row · Plan and usage · Upgrade or Billing
(billing on only) · On this device · Developer tools · Information · the
account-ending controls (sr-only heading "Security and account removal":
Sign out everywhere, Delete account).

- **Header.** "Account" and nothing else: the lede is gone (it changed text
  between states and moved the page).
- **Loading.** While the capability report or the session is unknown the
  panel shows the title and "Loading…" only (`useCapabilities().settled`).
  The "sign-in is not available" card no longer flashes on every load, and
  the device/information groups are drawn once, in their final place.
- **Identity row** (`IdentityRow`, class `acct-id`, no card): the email and
  a text control "Sign out" ("Signing out…"), run guard underneath. Sign
  out stays one tap away but is no longer a button.
- **Plan and usage** (`PlanUsageGroup`), for every signed-in account, with
  or without billing:
  - Plan name: "Free account" or "Plus" ("Paid plan" until 2026-11-14) (paid if `/api/billing` or
    `/api/free-runs` says so).
  - "N of L runs left today" is the card's strongest number (20px, weight
    700), above the smaller reset time. From `/api/free-runs`, falling back
    to `/api/billing`'s count; "Runs unavailable" if neither answered.
    "this month" only if `period` is. A device-scoped count adds "This
    browser" to the reset line.
  - "Video length" → "Up to 3 minutes" with the note "or 10 with your own
    Gemini key"; paid: "Up to 10 minutes" / "No Gemini key needed"; free
    with a saved key: "Up to 10 minutes" / "With your own Gemini key".
    Numbers are `/api/limits`' and are not quoted until that read and the
    plan have both answered (`useMediaLimits().settled`).
  - "Resets at" below the count uses `resets_at` in the reader's own time zone
    (`formatClockTime`, e.g. "7:00 PM" in New York). Never "midnight" or
    "tomorrow": the reset is UTC midnight. Unknown: "Reset time unavailable".
  - With a saved Gemini key no count is read, so the rows become "Runs" →
    "On your own Gemini key" and "No daily limit with your Gemini key".
  - The count, reset and video-length slots are held from first paint.
    Static muted placeholder lines replace blank pending values. Each slot
    reserves one line from 20rem up (every value measured to fit one line
    at 320px) and two below 20rem; Codex's two-line reservation under 40rem
    left a blank line under each value on a 412px phone (fixed 2026-11-14).
    No animation or bar. "Runs unavailable" is drawn muted at 600, not as
    the bold figure. If the plan read failed and neither the count nor the
    session's `/api/me` entitlement names the plan, the name is "Plan
    unavailable", not "Free account".
- **Upgrade / Billing:** `billing.md`.
- **On this device** (`DeviceGroup`): "Recent history" / "Saved in this
  browser · Up to 20 runs" (`HISTORY_LIMIT`,
  re-exported from `useRunHistory`), and "Your Gemini key (optional)" /
  Use your own Google AI access." "Not synced between devices" sits under
  the rows in every state. Signed in, the
  note "Both stay in this browser when you sign out."
- **Developer tools:** one collapsed row, "VideoLens API access" /
  "VideoLens API keys let other tools submit runs through your account."
  Same disclosure behaviour as before (fetch on first open, count, unseen
  secret flag). The row is drawn while `/api/me` is still loading, so it
  does not arrive late; opened that early it says "Loading your account…".
  Body copy says "VideoLens API key(s)" throughout.
- **Information** (was "Help"): Privacy policy, Terms of use, What's new.
  No support or contact row. Its group heading is regular weight; Plan and
  usage leads with a heavier heading and slightly more space below it.
  A hairline and padding separate account-ending actions; delete stays muted.
- **Signed out** (`SignedOut`): card heading "Get 10 free runs a day"
  (`ACCOUNT_FREE_RUNS_PER_DAY`), "Sign in or create an account with your
  email. No password needed.", the email field, help "We’ll email you a
  code. New here? Entering it creates your account.", "Send code". The code
  step is unchanged (resend, change email, expiry, errors). Under the card:
  the text link "Continue without an account" (to Analyze), then, muted,
  "An account also unlocks videos up to 10 minutes with your own Gemini
  key, and VideoLens API keys for scripts and other tools." (without a
  longer tier: "An account also gives you VideoLens API keys for scripts
  and other tools."). Then On this device and Information.
  "Send code" spans the available width on phones (up to 40rem); Verify is
  unchanged. Continue stays directly below the form.
- **Props.** `capabilitiesSettled`, `freeRunsPending`, `billingPending`,
  `limits` (the whole `MediaLimitsState`) are new; `paidMinutes` and
  `signInMinutes` are gone.
  `billingFailed` distinguishes a failed billing request from disabled
  billing, retaining the reserved group with an unavailable message.
- **Top gap.** `.acct-page` padding-top is `clamp(1.25rem, 0.75rem +
  2.4vw, 2.75rem)` (was the shared `clamp(1.875rem, …, 3.875rem)`).

Verified 2026-11-14 with Playwright at 412, 320 and 1280: signed out
against the local servers; free (billing off), free (billing on), paid and
free-with-a-key with the session and API responses mocked (staggered
250–1200 ms). No horizontal overflow; the panel contributes no layout
shift (the 0.001–0.002 left is the shared nav/dock when the Account entry
appears). Not exercised: the code step, checkout, sign-out, key actions.

## Known limits

- Legal and offline routes render `AppNav` without `showAccount`, so the
  Account tab is absent there (as on any route that does not read
  capabilities).
- The API keys section ships in phase 2 because the brief asked for it; the
  plan had it in phase 3. Deletion stays in phase 3.
- A row left `queued`/`processing` under another identity stays that way in
  History until that identity is back (the reconcile then settles it). It
  is not marked expired, on purpose.
- Errors on the email and code fields are `role="alert"` and also take
  focus, so a refusal after pressing Enter is announced.

## The 30-day deletion hold (2026-11-14)

`DELETE /api/me` now answers **200** `{"status": "pending_deletion",
"purge_at": "…"}` instead of 204: the account stops working at once and is
held for 30 days. `AccountGateway.deleteAccount()` returns `{purgeAt}` (null
for a legacy 204), `useAccountDeletion` hands it to the panel, and the
deleted card names the date. A retry whose 200 was lost gets 410
`account_pending_deletion`, which also counts as done. Signed in to a held
account, every route answers 410 `account_pending_deletion`; the API client
hears it whichever gateway asked, and the Account page shows the held card
with "Restore account" (`POST /api/me/restore`) and "Sign out".
`useAccount` maps the 410 to `problem.kind === "held"`. The delete form's
copy now explains the hold. Everything is in `saved-history.md`.

## Sign-out hides runs (owner decision, 2026-11-21)

Supersedes the first bullet of "Review fixes (2026-11-20)" below. Signing
out (every path) no longer touches History: the account's rows stay in this
browser, hidden until that account signs in here again (run-history.md,
"Sign-out hides, it does not delete"). `signOut()` is now only the
provider's sign-out. `signOutAndForgetRuns()` also removes the signed-in
account's own rows; account deletion and Sign out on the closed hold card
use it. Copy, final wording:

- Continue signed out: "Your account's runs stay in this browser, hidden
  from History until you sign in here again."
- "On this device", signed in: "Not synced between devices. When you sign
  out, your account’s runs stay in this browser, hidden from History until
  you sign in here again. On a shared computer, remove them under History
  before you sign out."
- Same, saved history: "Your Gemini key is not synced and stays in this
  browser when you sign out. This browser’s copies of your runs stay too,
  hidden from History until you sign in here again. On a shared computer,
  remove them under History before you sign out."
- Delete form lede: "... After that it is removed for good. Its runs also
  leave this browser's History." Kept note: "Deleting your account signs
  this browser out and removes your account’s runs from its History. ..."
- Closed hold: "... Sign out to keep using VideoLens without an account.
  Signing out also removes its runs from this browser's History. Once it is
  gone, ..."

## Review fixes (2026-11-20)

- **(Superseded 2026-11-21, see above.) Sign out removes the account's runs from this device.** `signOut()`
  (and so account deletion, "Continue signed out" and, on success, "Sign out
  everywhere") also removes every History row filed under a signed-in
  account; anonymous rows stay. Rule and mechanics in run-history.md,
  "Leaving this device". The "On this device" note now reads "Not synced
  between devices. Signing out removes your runs from this browser’s
  History; your Gemini key stays." (signed in, free), or "Your Gemini key is
  not synced and stays in this browser when you sign out. This browser’s
  copies of your runs are removed then; the copies saved to your account
  stay." (saved history). This supersedes "Both stay in this browser when you
  sign out." above.
- **A stored session that cannot be recovered.** `useAuthUser()` exposes
  `unconfirmed`: loaded, nobody in memory, a session still stored (the
  provider would not load or its refresh failed on the network). The panel
  draws "We can’t confirm your sign-in right now" with **Retry**
  (`AuthSession.recover()`: load again, or `getSession()` again; notifies,
  never rejects) and **Continue signed out** (`signOut()`, which clears the
  stored session and the account's rows). Anonymous use keeps working
  throughout; requests that would carry the session still fail as the
  retryable `NetworkError` they always did.
- **Sign-in keys unavailable (503 + `Retry-After`).** `ApiClient.reject`
  now reads `Retry-After` onto `ApiError.retryAfter`. On `GET /api/me` a 503
  with one (or with the sentence "Sign-in is unavailable right now.") is the
  new `unconfirmed` problem: "We can’t confirm your sign-in right now. The
  sign-in service is briefly unavailable; you are still signed in. Try again
  in a moment." with Try again, and nothing offers sign-out. A 503 without
  either is still "Sign-in is not available on this server".
- **Too many failed credentials (429).** A 429 whose detail is not the rate
  limit's "You're going a bit fast." sentence is shown as sent, so the
  credential limiter's own wait reaches the person (`createRunFailureMessage`).
- **New API key announced without the secret.** Only the lede ("{name} is
  ready. Copy it now…") is the live region; the card used to be, so a
  screen reader read the secret aloud.

## Re-review fixes (2026-11-20)

- **Signed-in creates never go out anonymous.** `ApiClient.bearer()` waits
  up to 8 s (was 4 s) for the server's auth status. Still unknown after
  that, or the token cannot be read, it throws `SignInUnconfirmedError`
  instead of sending the request without a bearer. A create then says
  "Your sign-in could not be confirmed just now, so the run was not sent.
  Check your connection and try again." Nobody signed in (no session
  stored) gets no bearer at once, with no wait.
- **The owner travels with the request.** `identityHeaders()` returns the
  owner it built the headers for, and `sendAs` uses that, never the shared
  `this.owner` read after an await.
- **Another tab's sign-out.** `AuthSession` hears the `storage` event for
  its key; the stored session gone while one is held in memory means signed
  out, and listeners are notified.
- **Analyze is cleared on sign-out** (`useAnalysisRun`, a session
  subscription): any sign-out path, account deletion, "Continue signed out"
  or another tab, or another person signing in. Only when the run on screen
  may be an account's (an anonymous run stays) and only after someone was
  signed in during this mount. The unconfirmed state (session stored, not
  recovered) and a 503 from `/api/me` never trigger it.
- **401 on a poll** is retried once, after about a second, so a token the
  provider refreshed in the meantime is used before the run is ended.
- Deletion copy: the account card and the deleted state now say the
  account's runs leave this browser's History (deletion signs out), and that
  runs made signed out and the Gemini key stay.

## Second re-review fixes (2026-11-21)

- **`degraded` is its own state.** `ServerAuthState` is now
  `unknown | ok | off | degraded`. The capabilities adapter maps the `auth`
  row `ok` → `ok`, `degraded` (the sign-in keys briefly unreachable) →
  `degraded`, anything else (`disabled`, a missing row, an unknown state) →
  `off`. It used to map `degraded` to `off`, so a signed-in person's
  requests went out anonymous for the rest of the page load and their runs
  were filed `anonymous`, surviving sign-out. With a session stored,
  `bearer()` treats `degraded` like `unknown`: it waits, and fails with the
  same retryable `SignInUnconfirmedError` message. No session stored: no
  change at all (no wait, no re-read).
- **The status recovers without a reload.** `MemoryServerAuthStatus.settled`
  resolves as soon as the state is `ok` or `off` (a `degraded` report does
  not end the wait), and asks for a fresh report when it starts waiting
  (`requestReport`). Reads are deduplicated twice over: the capabilities
  adapter shares one in-flight `fetchReport()` with every caller, and the
  status starts at most one read per 5 s, with one trailing read while
  someone is still waiting. So during an 8 s wait the report is read up to
  twice, and a failing backend sees at most one read per 5 s, only while a
  signed-in request is waiting. The reader is wired in `container.ts`
  (`serverAuthStatus.setReader`), so it works on every route.
- **Screens see the newer report.** `CapabilitiesGateway.subscribe` hears
  every report, whoever asked; `useCapabilities` and `useAccountEntry`
  listen, so a recovered `auth` row shows the Account tab and entry without
  a reload.
- **Opening a run decides ownership from the record.** `openRun` no longer
  lets a sign-out during the History read clear Analyze on its provisional
  "may be an account's" guess: the decision waits for the record
  (`ownerPendingRef`/`deferredLeaveRef` in `useAnalysisRun`), and only an
  account's (or unknown-owner) run is cleared.

## Changelog

- 2026-11-14 · Codex · emphasised runs left with reset below, shortened device descriptions, added static loading/failure feedback, separated ending actions, made Send code full width on phones, and adjusted section heading emphasis; browser verification unavailable this session

- 2026-11-08 · frontend subagent (auth phase 2) · created: Supabase adapter (dynamic import, PKCE, 4 s token wait), `ApiClient` with bearer/client-id/device-token on every caller request, `AccountGateway`, the three hooks, history re-import on sign-in, the Account tab and panel (OTP 6 to 8 digits, resend after 60 s, run guard, API keys with one-time secret and revoke confirm), the auth origin in the CSP. Verified: validation, unreachable error and hidden tab in a browser; `signInWithOtp` fires `POST /auth/v1/otp`, blocked by the running dev server's pre-change CSP until it restarts. Code step and signed-in view not exercised (no inbox)
- 2026-11-08 · frontend subagent (auth phase 2, review fixes) · `getToken` throws when a session exists but no token is available (load timeout, unrecovered stored session, failed refresh) and `ApiClient` turns it into a retryable `NetworkError`; bearer sent only when the server's `auth` capability is `ok` (`ServerAuthStatus`, fed by the capabilities adapter, bounded 4 s wait); History records `owner` and a 404 under a different identity is `other-owner` (screen message, History untouched) instead of expired; panel uses the same capability gate and keeps Sign out reachable when unavailable; one-time secret stripped from the key list; field errors are `role="alert"`. Signed-in view and key list confirmed rendering in the owner's signed-in browser profile
- 2026-11-08 · Codex · refined Account-only hierarchy, identity alignment, API-key form spacing and mobile wrapping using existing tokens; browser visual QA blocked by computer-access timeout
- 2026-11-08 · Codex · Account essentials pass: clearer email/code steps, read-only busy inputs and live progress, active-key count, signed-in introduction and corrected local-retention copy; typecheck and component lint passed
- 2026-11-08 · Codex · simplified Account into identity plus collapsed API-key, device-data and help/privacy sections; existing navigation and theme reused; typecheck, lint and mocked render checks passed
- 2026-11-09 · main session · reviewed Codex's diff and the panel in Chrome (desktop, both themes, disclosures, delete form opened and cancelled): renders correctly, no console errors; found dead `.acct-section-head` CSS, a tooling comment in `globals.css`, bullet-less delete lists and `next-env.d.ts` noise; phone width not verifiable from this Chrome window. Added the "Phase 3 state and remaining work" section
- 2026-11-09 · frontend subagent (auth phase 3) · hygiene: removed dead `.acct-section-head` CSS and the tooling comment, disc markers on `.acct-delete-list`, reverted `next-env.d.ts`; verified class usage, single `AccountResources` render and the `DELETE /api/me` status mapping; tsc clean, build and build:mobile pass, lint 5 known findings only; changelog put in date order (the `?`-separator duplicate was already gone), refinement section corrected on the key count and delete-card background
- 2026-11-09 · frontend subagent (auth phase 3, review fix) · "Back to sign in" on the deleted card is held (`aria-disabled`, guard, status line) until `signOut()` settles, via a promise passed to `onDeleted`, so the old session cannot re-create the account; `rejected` deletion copy reworded to stay true when a lost-204 retry gets 401; tsc clean, build and build:mobile pass, lint 5 known only
- 2026-11-09 · frontend agent · privacy page deletion sentence corrected (backups and logs ~7 days)
- 2026-11-09 · frontend agent · Account tab option A layout; sign out everywhere
- 2026-11-13 · frontend agent · desktop top bar: Account text tab replaced by a round icon link at the far right (person glyph signed out, email initial signed in, filled ink when current); phone menu, More sheet and dock unchanged
- 2026-11-13 · frontend agent · Account panel free-runs line is scope-aware ("Free runs left this month: N of 10" for the account allowance); `AccountPanel` prop `freeRunsLeft` → `freeRuns`; HomeScreen re-reads free runs when the signed-in user changes
- 2026-11-13 · frontend agent · signed in + saved Gemini key unlocks the larger upload tier (10 min / 500 MB from `GET /api/limits`); signed out with a key, the drop well says "Sign in for videos up to 10 minutes." (link to Account) where sign-in is offered. See `upload-form.md`, "Upload limits per tier"
- 2026-11-13 · frontend agent · Account gains a "Plan" group above "Your account" (only when the `billing` capability is ok and `/api/billing` says enabled), a checkout-return notice under the header, and "Runs left this month: N of L" on the identity line for a paid account; props `billing`, `checkoutReturn`, `paidMinutes`. See `billing.md`
- 2026-11-13 · frontend agent · account deletion: 503 `subscription_cancel_failed` gets its own message (nothing deleted, account and subscription unchanged), form stays usable. See `billing.md`
- 2026-11-14 · frontend agent · Account moves into the installed-app dock as a 4th item (Analyze / History / Account / More, `CircleUserRound`, `aria-current` on `?view=account`) under the same `showAccount` gate; the More sheet's Account row is removed; top-bar round button unchanged
- 2026-11-14 · frontend agent · signed out, the ≥48rem top-bar Account control is a labelled "Sign in" pill (secondary voice, 44px); signed in keeps the round initial; nothing drawn until the session is known (`accountState` prop); phone-menu row reads "Sign in" signed out; dock unchanged; signed-out Account lede now lists 10 free runs a month, longer videos with your own key (minutes from limits), and API keys
- 2026-11-14 · frontend agent · Account entry (Sign in pill / initial / phone-menu row / dock item) on landing, Privacy, Terms and 404 via `RouteNav`/`RouteTabBar` + `useAccountEntry` (same gate, one shared capability read); `/offline` left out (no network)
- 2026-11-14 · frontend agent · landing's signed-out entry reads "Get started" (`signedOutLabel` prop on AppNav/RouteNav, outlined, not green beside the hero's green CTA); other routes keep "Sign in"; sign-in card heading "Sign in or create an account", help line "New here? Verifying your first code sets it up."
- 2026-11-14 · codex · landing nav and phone menu back to the default "Sign in", so the account entry reads differently from the no-account "Start analyzing"; the `signedOutLabel` prop stays
- 2026-11-14 · frontend agent · landing signed-out entry reads "Get 10 free runs" (10 from `ACCOUNT_FREE_RUNS_PER_MONTH`, now in `application/accountAllowance.ts`), bar pill and phone-menu row; new `signedOutShortLabel` prop: the bar pill says "Sign up free" from 48rem to 50rem, where the long label overran the gutter by 13px; other routes keep "Sign in"
- 2026-11-14 · frontend agent · daily account allowance: signed-out lede "Sign in for 10 free runs a day, ..."; identity line "Free runs left today: N of 10" (from `period`)
- 2026-11-14 · frontend agent · Account refinement (six items): compact identity row with a text Sign out; Plan and usage card for every account (plan, runs left, video length, reset in local time; rows reserved); signed-out card leads with "Get 10 free runs a day" + "Continue without an account"; "VideoLens API access" under a collapsed Developer tools group; "Recent history" / "Your Gemini key (optional)" wording; Help renamed Information; lede removed; Loading state until capabilities settle; top gap trimmed
- 2026-11-14 · frontend agent · delete-account note says "under History and Gemini key" (tab renamed); paid Billing card gains "Extra runs this month" (see billing.md); new pre-paint `data-session` stamp and `useStoredSessionHint()` (`infrastructure/authSessionStamp.ts`; `providerStorageKey` now shared with `SupabaseAuthSession`), used only to hold layout on the Gemini key page (see byok-api-key.md)
- 2026-11-14 · frontend agent · reviewed Codex's Account refinements in the browser (320-1440, both themes, both shells, signed out / free / paid with and without `extra_runs` / loading / failed); one-line value reservations from 20rem, framed billing stand-in, muted "Runs unavailable", "Plan unavailable" instead of a false "Free account" when the plan read failed
2026-11-14 · frontend agent · `DELETE /api/me` now answers 200 `{status, purge_at}` (30-day hold; legacy 204 still handled); delete form, deleted card and the new held/restore states rewritten for the hold; `AccountProblem` gains `held`; `useAccount` re-reads after a restore (see saved-history.md)
- 2026-11-14 · frontend agent · paid plan is named Plus in the UI (Plan card name)
- 2026-11-14 · orchestrator · `frontend/Dockerfile` declares the two `NEXT_PUBLIC_SUPABASE_*` values as build ARGs; without them the Railway dev build had no sign-in
- 2026-11-14 · frontend agent · `AccountEntitlement.complimentary` typed; the Plan and usage card reads it (complimentary Plus: "Plus" plus "Complimentary. Nothing to pay."), see billing.md
- 2026-11-20 · Claude (frontend agent) · sign-out clears account-owned History rows; `unconfirmed` session state with Retry / Continue signed out (`AuthSession.recover`); keys-unavailable 503 on /api/me shown as temporary with no sign-out; `ApiError.retryAfter`; new-key status announces the sentence, not the secret; device-group note copy
- 2026-11-20 · Claude (frontend agent) · bearer waits 8 s then fails with `SignInUnconfirmedError` (never anonymous); owner returned by `identityHeaders`; cross-tab sign-out via `storage`; Analyze reset on sign-out; one 401 retry on polls; deletion copy corrected
- 2026-11-21 · Claude (frontend agent) · `degraded` auth kept as its own state (never anonymous with a session); capabilities re-read while a signed-in request waits (deduplicated, 5 s spacing), wait ends as soon as the state is decisive; `CapabilitiesGateway.subscribe` so screens see the newer report; `openRun` decides sign-out clearing from the record's owner
- 2026-11-21 · Claude (frontend agent) · sign-out hides account runs (owner decision): Account notes, Continue signed out, delete and closed-hold copy, RUN_GUARD wording; sign-in/out held only for a submit or a healthy followed run (`holdsSignIn`)
- 2026-11-22 · frontend agent · run guard needs a recent server answer (15 s, `HOLD_FRESH_MS`), so Sign out is never held on a status the screen stopped refreshing
- 2026-11-22 · frontend agent · OTP is exactly 6 digits (`CODE_LENGTH`, paste cut to six, placeholder `123456`); Google sign-in (auth phase 4) on web and Android: `AuthSession.signInWithGoogle` + redirect result, `AuthRedirectBrowser` port, `SystemAuthBrowser` adapter (`@capacitor/browser` 8.0.5), deep link `ai.videolens.app://auth/callback`, `detectSessionInUrl` off, button and "or" divider on the signed-out card; dashboard requirements listed
- 2026-11-22 · frontend agent · signed-out sign-in card reworked to the owner's reference layout: full-width equal-height stack (Google, uppercase OR, email with sr-only label and "Enter your email" placeholder, primary "Continue with email" replacing Send code with the same behaviour), centred Terms/Privacy note with no marketing clause; checked light, dark and phone content width
- 2026-11-26 · Claude (apk-supabase-config agent) · Android build configuration: CI now compiles the per-lane Supabase URL and publishable key into the APK (they were missing, so CI APKs up to v2.3.0-build543 had sign-in off) and fails a device-bound build without them; QA note on CI vs local APKs and the shared callback scheme
