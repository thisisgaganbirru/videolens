# Account panel

The `account` tab: who you are, your plan and minutes, the upgrade cards, billing management, and (on plans with API access) the API keys. Renders honestly on every deployment shape, from "no identity provider configured" up to a paid workspace.

**Files**
- `frontend/components/panels/AccountPanel.tsx` — the panel. Four shapes: no provider (`NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` unset) → limits only; signed out → sign-in button + limits; signed in without server storage (`accounts_enabled: false`) → identity + limits; signed in with storage → identity, `UsageMeter` (a `progressbar`), `PlanCards`, billing link, `ApiKeysSection`. Reads `?checkout=success|cancelled` once in a lazy `useState` initializer and scrubs it with `history.replaceState`.
- `frontend/application/useAuthSession.ts` — `{enabled, ready, user, signIn, signOut}` over the `AuthSession` port.
- `frontend/application/useAccount.ts` — `useAccount(userId)` → `{account, error, reload, upgrade(plan), manageBilling(), busy, actionError}`; `upgrade`/`manageBilling` navigate to the URL the backend returns.
- `frontend/application/useApiKeys.ts` — `useApiKeys(enabled)` → `{keys, create, revoke, justCreated, dismissSecret, busy, error}`. The secret is held in state only until dismissed; it is never stored.
- `frontend/domain/plans.ts` — `PLAN_CARDS` (display copy per plan), `isPlan`, `isUpgrade`. Numbers mirror `backend/app/domain/entitlements.py`; the backend is authoritative, these are labels.
- `frontend/domain/entities.ts` — `AccountResponse`, `UsageSummary`, `WorkspaceSummary`, `ApiKeySummary`, `ApiKeyCreated`, `AuthUser`.
- `frontend/domain/ports.ts` — `AuthSession`, `AccountGateway`.
- `frontend/infrastructure/authSession.ts` — `ClerkAuthSession` (dynamic `import("@clerk/clerk-js")` so the bundle carries nothing when unconfigured; `getToken()` returns the session JWT) and `NullAuthSession`; `buildAuthSession()` picks by env.
- `frontend/infrastructure/apiClient.ts` — the shared transport every gateway uses: `X-Client-ID`, `X-Gemini-Api-Key`, and `Authorization: Bearer <token>` when signed in; `ApiError` now carries `code` and `status`.
- `frontend/infrastructure/accountGateway.ts` — `FetchAccountGateway` over `/api/me`, `/api/keys`, `/api/billing/*`.
- `frontend/app/globals.css` — the ACCOUNT block (`.account`, `.usage*`, `.plan-grid`, `.plan-card`, `.key-*`).

**Rules**: upgrade buttons appear only when `billing_enabled` and the card is an upgrade over the current plan. The API-keys section mounts only when `account.api_access` and the caller is signed in with an `account_id`. "Manage billing" shows only when `has_subscription && billing_enabled`. Nothing here decides entitlements; it renders what `GET /api/me` says.

**Config**: `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` in `frontend/.env.local` (see `frontend/.env.example`). Unset means no sign-in UI at all, which is today's anonymous product.

**Tests**: none (the frontend has no test suite; `tsc --noEmit`, `eslint`, and `next build` are the gates).

## Changelog
- 2026-09-17 · main session · created with the account tab, Clerk adapter, and API-key UI
