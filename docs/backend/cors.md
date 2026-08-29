# Browser CORS configuration

The API accepts browser requests only from the comma-separated origins in
`ALLOWED_ORIGINS`. Local defaults include both `http://localhost:3000` (the
Docker Compose frontend) and `http://localhost:3005` (the `npm run dev`
frontend).

**Files**
- `backend/app/infrastructure/config.py` parses `ALLOWED_ORIGINS` through
  `Settings.allowed_origin_list`.
- `backend/app/interface/api/app.py` passes that list to FastAPI's
  `CORSMiddleware`.
- `backend/.env.example` and `docker-compose.yml` define local defaults.

When adding a deployed frontend, set `ALLOWED_ORIGINS` to its exact origin.
Multiple origins must be comma-separated. Restart the API after changing the
environment because middleware is configured when the module is imported.

The accepted request headers are `Authorization`, `Content-Type`,
`X-Client-ID`, and `X-Gemini-Api-Key`; the accepted methods are `GET`, `POST`,
and `OPTIONS`.

## The Android app's origin is not configurable

`Settings.allowed_origin_list` always appends `NATIVE_APP_ORIGINS`
(`https://localhost`, `http://localhost`) to whatever `ALLOWED_ORIGINS`
contains, de-duplicated. **Do not remove this, and do not expect
`ALLOWED_ORIGINS` to carry it.**

The Capacitor Android WebView serves the bundled Next.js export from inside
the APK under the hostname `localhost` — nothing listens on a port and no
traffic leaves the device; it is only how Chrome names the page it renders
(`https` is Capacitor's default `androidScheme`, which
`frontend/capacitor.config.ts` does not override). Every API call from the
APK is therefore cross-origin and arrives stamped `Origin: https://localhost`.

Note this is a *different* `localhost` from the one in
`NEXT_PUBLIC_API_BASE_URL`. That one is the request's **destination** — when
it was wrong, the APK called the phone itself and never reached Railway at
all (fixed in PR #20). This one is the caller's **identity**, which is
correct and fixed by the native shell; the server just has to recognise it.

These are constants of the native shell rather than a per-deployment detail,
which is why they live in code. Left to configuration, every new environment
ships an APK that fails its preflight with a bare 400 — and because
`frontend/infrastructure/runsGateway.ts` cannot distinguish a blocked
preflight from an unreachable host at the `fetch` level, the user sees
"Can't reach the server. It may be offline, or your connection dropped."
This exact failure hit the dev deployment on 2026-08-20 and cost a full
diagnosis round-trip through the Railway HTTP logs to identify.

## Diagnosing a suspected CORS failure

A rejected preflight is invisible from the client — the app reports an
offline server. Check the backend's Railway **HTTP logs** instead: an
`OPTIONS` to the endpoint returning `400` is `CORSMiddleware` refusing the
origin. `400` on a preflight only ever means a disallowed origin, method, or
header, so once the method and header lists are known good, it is the origin.

## Tests

- `backend/tests/infrastructure/test_config.py` — native origins are always
  present, never duplicated, and survive an empty `ALLOWED_ORIGINS`.
- `backend/tests/interface/api/test_cors.py` — drives a real preflight
  through the assembled app: `https://localhost` gets `200`, an unrelated
  origin gets `400`.

## Changelog

- 2026-08-20 · main session · always allow the Capacitor Android WebView origins in code; documented why the APK's `Origin` is `https://localhost` and how to spot a rejected preflight in the Railway HTTP logs
