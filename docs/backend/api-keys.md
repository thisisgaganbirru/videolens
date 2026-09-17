# API keys

Workspace-scoped keys for the MCP server, scripts, and anything else that is not a browser. Included with the Studio and Scale plans (`Entitlement.api_access`).

**Files**
- `backend/app/application/api_keys.py` — `ManageApiKeysUseCase`: `issue` (owner only, at most 10 active keys, name trimmed to 80 chars), `list` (any member), `revoke` (owner only). `PermissionDeniedError` (403) when the plan has no API access or the caller is not the owner; `WorkspaceNotFoundError` (404) when signed out or the database is off.
- `backend/app/infrastructure/persistence/api_key_repository.py` — `PostgresApiKeyRepository`. Secret format `vl_live_<8 hex>_<urlsafe 32>`; only `sha256(secret)` and the `vl_live_<8 hex>` prefix are stored. `authenticate` looks up by hash, refuses revoked keys, and stamps `last_used_at`. `looks_like_api_key` is what `get_principal` uses to route a `Bearer vl_live_…` to this path instead of the JWT verifier.
- `backend/app/interface/api/routes.py` — `GET /api/keys`, `POST /api/keys` (`{name}` → 201 with the secret, shown once), `DELETE /api/keys/{key_id}` (204).
- `backend/app/interface/api/dependencies.py` — `X-Api-Key: vl_live_…` or `Authorization: Bearer vl_live_…` resolves to `Principal(subject="key:{key_id}", method=API_KEY, workspace_id, plan)` before any JWT check; an unknown key is 401 `Invalid API key.`

**Scopes**: every key is issued with `runs:write` and `runs:read`; scopes are stored and returned but not yet enforced per route (nothing narrower exists to enforce). Rate limiting keys on the bearer's hash via the existing `quota_key_from_headers`.

**Tests**: `tests/application/test_api_keys.py`, `tests/infrastructure/persistence/test_sql_adapters.py` (issue/authenticate/revoke through SQLite), `tests/interface/api/test_account_routes.py` (401 on anonymous, bad key).

## Changelog
- 2026-09-17 · main session · created with the API key use case, repository and routes
