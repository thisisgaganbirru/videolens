# Authentication & caller identity

Resolves every request to a `Principal` (an owner id + whether they're authenticated) — either via an OIDC bearer token or an anonymous, self-issued client id.

**Files**
- `backend/app/interface/api/dependencies.py` — `get_principal`, the FastAPI dependency every route uses.
- `backend/app/infrastructure/auth/jwt_verifier.py` — `JwtVerifier` (+ `AuthNotConfiguredError`), implements `TokenVerifier`.
- `backend/app/domain/policies.py` — `is_valid_client_id` (regex: `^[A-Za-z0-9._:-]{16,128}$`).
- `backend/app/domain/entities.py` — `Principal`.

**Flow**: if `Authorization: Bearer <token>` is present, decode via `JwtVerifier.decode` (JWKS lookup + RS256/ES256 verification against `AUTH_JWKS_URL`/`AUTH_ISSUER`/`AUTH_AUDIENCE`) → `Principal(subject=f"user:{sub}", authenticated=True)`. Any decode failure (invalid signature, expired, wrong audience, JWKS unreachable) becomes a generic `401 "Invalid access token."` — except specifically when OIDC isn't configured at all, which is `503 "Authentication is not configured."` (that distinction is why `AuthNotConfiguredError` is a separate exception type rather than folding into the generic case).

Otherwise, falls back to anonymous: requires `allow_anonymous` (default true) and a valid `X-Client-ID` header → `Principal(subject=f"client:{client_id}", authenticated=False)`. The client id is self-reported by the frontend (a `crypto.randomUUID()` persisted in `localStorage`) — it scopes *which runs a browser can see*, not a quota identity (quota keying uses IP/token instead, see `cost-abuse-protection.md`).

**Status**: OIDC verification is implemented but not enabled by default (`allow_anonymous: true`). Per root `README.md`, going fully non-anonymous requires actually configuring an identity provider first — not something flip a flag alone accomplishes.

**JWKS caching (2026-11-07)**: `JwtVerifier` keeps one `PyJWKClient(cache_keys=True, lifespan=600)` for its lifetime. It used to build a new client per `decode`, which fetched the JWKS on every authenticated request - a round trip of latency each and a way for anyone with a token to make this service hammer the identity provider. PyJWT still refetches on an unknown `kid`, so key rotation is unaffected.

**Tests**: `backend/tests/infrastructure/auth/test_jwt_verifier.py` (unconfigured auth is `AuthNotConfiguredError`; one caching JWKS client across calls; only RS256/ES256 with audience and issuer). None for `get_principal` itself. `is_valid_client_id`'s underlying pattern has no dedicated test either, though it's simple enough to read at a glance.

## Changelog
- 2026-11-07 · security-check · `JwtVerifier` reuses one caching `PyJWKClient`; first tests for the verifier
