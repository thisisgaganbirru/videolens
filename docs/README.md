# docs/

This project's docs/ folder holds quick per-feature/component reference docs — what a feature does, what files it touches, known issues — so it can be understood without reading all the source. It does NOT replace `README.md`, the root `CLAUDE.md`, `DEPLOYMENT.md` or the two `ARCHITECTURE.md` files; those cover onboarding, high-level architecture, and release process, not per-feature reference.

Every new feature or component should get (or update) a doc here. Scope is strictly the feature/component you're actively touching this session — never a retroactive sweep to document the rest of an existing codebase. Pre-existing features stay undocumented until someone actually touches them.

## Index

### Backend (`backend/`)

| Doc | Covers |
|---|---|
| `run-intake.md` | `POST /api/runs`: validation, admission, enqueueing (`CreateRunUseCase`) |
| `run-processing.md` | The pipeline: download/normalize/analyze/persist, the caption fallback, the poster, refunds, abandoned runs |
| `run-storage.md` | `RunStore`, Redis vs in-memory, `RUN_TTL_SECONDS`, `GET /api/runs` |
| `media-validation.md` | FFmpeg validation, the resolver chain, yt-dlp, the SSRF guard, cookies |
| `gemini-analysis.md` | The Gemini engine: prompts, structured output, retries, fallback model, caption-only analysis, source context |
| `job-queue.md` | arq vs the in-process runner |
| `object-storage.md` | S3-compatible temporary storage |
| `cost-abuse-protection.md` | Rate limit, daily cap, BYOK asymmetry, `Retry-After` |
| `free-runs.md` | The per-device daily free-run allowance: device tokens, `GET /api/free-runs`, the 401/402 codes, refunds, how easy it is to bypass |
| `byok.md` | Bring-your-own-key and the single-use key vault |
| `auth.md` | `get_principal`, OIDC bearer tokens, `X-Client-ID` |
| `cors.md` | `ALLOWED_ORIGINS` and the native WebView origins |
| `capabilities.md` | `GET /api/capabilities` and the probes |
| `releases.md` | `GET /api/releases`, read from GitHub server-side |
| `security-headers.md` | The hardening headers every API response carries |

### Frontend (`frontend/`)

| Doc | Covers |
|---|---|
| `app-shell-layout.md` | The one-viewport frame, the two shells (web / installed app), URL tabs |
| `design-direction-editorial.md` | **The live visual system** (tokens, type, shell modes, contrast table). Read before any UI work |
| `design-direction-terminal.md` | Superseded history, kept for provenance |
| `landing-page.md` | The landing page at `/`, the tool's move to `/app`, the pre-paint redirects, the Capacitor `.html` hop |
| `first-run.md` | The installed app's cold-start splash and one-time Welcome |
| `upload-form.md` | The intake form |
| `run-status-pipeline.md` | The progress view while a run processes |
| `results-view.md` | The finished result: notes, transcript, screen text, export |
| `run-analysis-hook.md` | `useAnalysisRun`: submit/poll/open/reset, the active-run store |
| `run-history.md` | History in IndexedDB, the poster grid, filters and sort |
| `free-runs.md` | The client half of free runs: device token, banner, 401 retry and 402 handling |
| `byok-api-key.md` | The API key tab |
| `capability-reporting.md` | The capability notice and callouts |
| `release-notes.md` | The Releases tab |
| `android-update-check.md` | The native update check and `UpdatePrompt` |
| `share-intake.md` | A link handed to the app from outside it (Android share intent, web share target) |
| `legal-offline-routes.md` | `/privacy`, `/terms`, `/offline` |
| `web-manifest.md` | `manifest.ts` |
| `security-headers.md` | The CSP (web header, hash-based meta in both builds), the other security headers, Android backup rules |
| `seo-and-discovery.md` | Per-page metadata, canonicals, sitemap.xml, robots.txt, the social preview image, favicon.ico, the noindex switch, and the 2026-11-12 launch-checklist audit |

### Cross-cutting

- `qa/android-app-test-cases.md` — the full manual test suite for the
  installed Android app (bundled APK, never live reload).
- `qa/web-app-test-cases.md` — the full test suite for the web app in a
  browser tab (production build on a spare port, `/api` mocked with Playwright,
  real backend only for the real-run cases).
- `container-workflows.md` — local/dev/production workflow boundaries, the CI
  lanes, hardened container behavior, image publication, runtime-version
  policy and operator requirements. Read before editing a workflow.
- `error-messaging.md` — how a failure becomes a sentence on screen and where
  the operator's half of it goes. Spans backend and frontend, so it is filed
  here rather than under either.
- `railway-environments.md` — the two Railway environments, which branch
  feeds each, how `Wait for CI` gates deploys, and the three ways a deploy
  silently does not happen. Read before changing a trigger branch.
- `images/` — the README screenshots. Regenerate with
  `scripts/readme-screenshots.js` (mocked API, fixture data) after a visual
  change, so the README never shows a design the app no longer has.
- `engineering-standards.md` — cross-cutting, not a per-feature reference. A
  repo-wide engineering-hygiene register audited 2026-08-15, with resolution
  notes where work has landed. Also records the decision to keep the MCP
  server parked on `feature/mcp-server`.

## Applies to subagents too — no exceptions

**Every agent and subagent follows this, not just the main session.** If you were
dispatched to do a piece of work, you read the relevant doc here *before*
starting and update it *before* reporting back. "The orchestrator will document
it" is not an exemption — the agent that did the work is the one that knows what
changed and why.

## Changelog line (required)

When you touch a doc, append one line to its `## Changelog` section (create the
section if absent) so the next agent can see what has already been done and by
whom, instead of re-deriving it or redoing it:

```markdown
## Changelog
- 2026-08-15 · frontend agent · ported the legal routes to the shared app chrome; added the crumb bar
- 2026-08-15 · main session · deleted the dead Midnight Glass classes after their last caller was ported
```

Format: `YYYY-MM-DD · <who> · <what changed, one line>`. Newest last. `<who>` is
the agent type (`frontend agent`, `main session`, …). Keep it to one line — the
detail belongs in the doc body and in `mem/`.

**Several agents share these files.** Read the changelog before editing so you
don't duplicate or revert a sibling's work, and append rather than rewriting
someone else's entry.

## Changelog

- 2026-08-15 · main session · indexed the environment-separated container workflow reference and updated the standards status
- 2026-08-21 · main session · indexed the cross-cutting error-messaging reference
- 2026-08-29 · main session · indexed `railway-environments.md`
- 2026-08-29 · main session · added `backend/releases.md` for the new `GET /api/releases` endpoint
- 2026-11-01 · frontend agent · indexed `frontend/design-direction-editorial.md` as the current design direction
- 2026-11-01 · backend agent (Phase 5b) · indexed `backend/free-runs.md`
- 2026-11-01 · frontend agent (Phase 5b) · indexed `frontend/free-runs.md`; renamed the quick-links heading to cover both halves
- 2026-11-01 · frontend agent (Phase 5c/5d) · indexed `frontend/landing-page.md` and `frontend/first-run.md`
- 2026-11-02 · frontend-43 · indexed `qa/web-app-test-cases.md` next to the Android suite
- 2026-11-07 · main session · replaced the quick-links sections with a full index of every backend and frontend doc
- 2026-11-07 · frontend agent · indexed `frontend/security-headers.md`
- 2026-11-07 · main session · added `images/` (README screenshots) and the script that regenerates them; indexed both `security-headers.md` docs
