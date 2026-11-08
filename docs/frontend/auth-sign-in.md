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
- **Signed in:** the email and Sign out; API keys (create with a name, the
  secret shown once with Copy and Done, the list with prefix, created, last
  used, revoked, and an inline "Revoke? / Keep" confirm); one sentence that
  account deletion is coming (phase 3). No delete control.
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
- **Run guard (on screen):** Verify and Sign out are also held, with a note,
  while the run on Analyze is submitting, queued or processing
  (`runInProgress`), so the watched run is not interrupted at all.
- Busy controls use `aria-disabled` and handler guards, never `disabled`,
  so focus is not lost (the app-wide rule).

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
