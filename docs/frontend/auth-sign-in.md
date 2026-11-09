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

## Layers

| Layer | File | Role |
|---|---|---|
| domain | `entities.ts` | `AuthUser`, `AccountResponse` (+ `AccountWorkspace`, `AccountEntitlement`), `ApiKeySummary`, `ApiKeyCreated`, `ApiKeyListResponse` |
| domain | `ports.ts` | `AuthSession` (`enabled`, `load`, `user`, `hasSession`, `getToken`, `requestEmailCode`, `verifyEmailCode`, `signOut`, `subscribe`; no Google method yet), `AccountGateway` (`fetchAccount`, `listKeys`, `createKey`, `revokeKey`), `ServerAuthStatus` (the server's `auth` capability: `unknown`/`ok`/`off`), `CallerIdentity` (`lastOwner()`) |
| domain | `entities.ts` (History) | `HistoryRecord.owner`: `user:<id>` or `anonymous`, the identity the run was created or imported under |
| domain | `errors.ts` | `AuthFlowError(reason)`, reasons `invalid_email`, `invalid_code`, `rate_limited`, `unreachable`, `unavailable`, `unknown` |
| infrastructure | `authSession.ts` | `SupabaseAuthSession` and `NullAuthSession`, `buildAuthSession()`. The only file that names Supabase |
| infrastructure | `apiClient.ts` | The shared caller transport: `X-Client-ID` always, `X-Device-Token` when held, `Authorization: Bearer` only when signed in **and** the server's `auth` capability is `ok`. Records the identity each request went out as (`lastOwner`) |
| infrastructure | `serverAuthStatus.ts` | `MemoryServerAuthStatus`, fed by `FetchCapabilitiesGateway` from every report's `auth` row (a report without the row counts as `off`) |
| infrastructure | `accountGateway.ts` | `/api/me`, `/api/keys` (GET, POST), `DELETE /api/keys/{id}` |
| infrastructure | `container.ts` | `authSession`, `serverAuthStatus`, `apiClient` (also exported as `callerIdentity`), `accountGateway`; `runsGateway` and `freeRunsGateway` now take the `ApiClient` |
| application | `useAuthSession.ts` | `useAuthUser()` (who is signed in, `ready`), `useEmailCodeSignIn()` (the OTP form state), `signOut()` |
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
  `flowType: "pkce"`, `detectSessionInUrl` on web only (false inside
  Capacitor; it only matters for the Google redirect in phase 4).
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

## Emailed code (the only method this phase)

- `signInWithOtp({ email, options: { shouldCreateUser: true } })`, then
  `verifyOtp({ email, token, type: "email" })`.
- The code field accepts **6 to 8 digits** (`inputmode="numeric"`,
  `autocomplete="one-time-code"`). `videolens-dev` sends 8; the plan's
  "6 digits" was Supabase's old default. Pasted text is reduced to digits.
- Copy says the code expires in 10 minutes (the project's 600 s setting).
- Resend is offered after 60 s (Supabase refuses a second code sooner), with
  a visible countdown. "Use a different email" goes back to step one.
- Google has no button. It is phase 4 (`auth-plan.md`).

## The Account tab

- **Shown** only when `authSession.enabled` *and* the server's `auth`
  capability is `ok`. Computed in `HomeScreen` and passed to `AppNav`,
  `BottomTabBar` and `MoreSheet` (`navTabs(showAccount)`).
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

## Changelog

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
