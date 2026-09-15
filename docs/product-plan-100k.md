# VideoLens AI → $100k ARR: product and engineering plan

Written 2026-09-15 against `dev` at v2.1.1. Strategy, not a feature doc: it
says what to build, why, in what order, and what it costs. Per-feature docs
under `backend/` and `frontend/` remain the reference for how each piece works
once built. "$100k" here means $100k annual recurring revenue.

## Where the codebase is today

- **Product**: upload MP3/MP4/MOV (≤200 MB, ≤3 min) or paste a public URL,
  get title, summary, timestamped transcript, timestamped on-screen text, and
  markdown notes from one Gemini call. Caption-track salvage when the download
  fails. Terminal-style Next.js PWA plus a Capacitor Android app with
  share-sheet intake.
- **Money**: none. No accounts, no billing. Cost is bounded by a per-IP rate
  limit, a global daily run cap, and BYOK (the user's own Gemini key, exempt
  from the daily cap).
- **Identity**: a spoofable `X-Client-ID` header scopes history. OIDC JWT
  verification is implemented in `jwt_verifier.py` but disabled.
- **Storage**: Redis only, 20 runs per caller, 7-day TTL. Nothing durable.
- **Health**: 178 backend tests pass, `tsc --noEmit` is clean, CI publishes
  GHCR images and an APK from `main`. Roughly 16 commits over three months.
- **Gap**: the root `CLAUDE.md` describes an `mcp/` server (analyze_video,
  list_recent_runs, mandatory BYOK, `~/.videolens/client_id`). That directory
  does not exist on `dev`, `main`, or any feature branch. Treat it as
  planned-but-unbuilt.
- **License**: AGPL-3.0.

## 1. The big idea

### The wedge

Stop selling "video → notes". Transcription is a commodity at roughly
$0.006/min and every Whisper wrapper does it.

Sell the one thing the pipeline already does that transcription tools
structurally cannot: **it reads the screen.** `SYSTEM_INSTRUCTION` in
`backend/app/infrastructure/ai/gemini_engine.py` asks Gemini for
`screen_text` and `screen_text_segments`: burned-in captions, CTA overlays,
code, slide text, UI labels, chart numbers, timestamped and fused with the
speech into one explanation. That is the moat, and it is built.

**Positioning: "Read what the video shows, not just what it says."**

**Primary customer (the money): short-form creative strategy teams.** UGC
agencies, performance-marketing teams, brand social teams. Their daily job is
teardown: pull 50–300 competitor Reels/TikToks/Shorts a month and extract the
hook, the on-screen caption, the CTA overlay, the offer, the beat structure.
Burned-in text *is* the creative in that format. They have tool budgets
($100–500/mo for Foreplay, Motion, Atria). The 3-minute cap is not a
limitation for them; it is the native content length.

**Secondary (distribution, not revenue): developers and agent users.** The
`mcp/` server is a credible, shareable, zero-CAC story ("Claude Code can watch
a video") into a population that will pay $19/mo and never generate enough
volume to hurt margins. Build it because it feeds the funnel and gives the
open-source repo a reason to be starred.

**Tertiary (defer to Phase 3): technical content and devrel teams** turning
demo recordings, talks, and Looms into docs. Needs the duration cap lifted,
which is Phase 1 work anyway.

Why teams first: it changes the arithmetic. 700 prosumers at $12/mo is a
marketing company. ~100 workspaces at $79/mo is a sales-and-SEO job a solo
developer can do.

### Unit economics

Meter **minutes of media**, not runs. Gemini bills video by token, tokens
scale linearly with duration, and "a run" stops meaning anything once the
3-minute cap comes off.

Gemini tokenizes video at roughly 258 tokens/frame at 1 fps plus ~32
tokens/sec of audio, about **290 tokens per second** at default media
resolution, or about 100 tokens/sec at `MEDIA_RESOLUTION_LOW`. Using
Flash-class pricing (~$0.30/M input, ~$2.50/M output). **Verify against
current AI Studio pricing for `gemini-3.6-flash` before publishing a price.**

| Item | 3-min video (default res) | 60-min video (low res) |
|---|---|---|
| Input tokens | ~52,000 | ~360,000 |
| Input cost | $0.016 | $0.108 |
| Output tokens (transcript + segments + screen text + notes) | ~6,000 | ~45,000 |
| Output cost | $0.015 | $0.113 |
| Retry allowance (`analyze_with_retry`, 2 attempts) +10% | $0.003 | $0.022 |
| **Gemini subtotal** | **$0.034** | **$0.243** |
| Infra (Railway CPU for transcode, RAM, egress, S3) | ~$0.004 | ~$0.05 |
| **COGS** | **~$0.038** | **~$0.29** |

Budget **$0.013 per minute of media** at default resolution, ~$0.005/min at
low resolution.

| Tier | Price | Included min/mo | Full-use COGS | Full-use GM | Realistic use (30–40%) | Realistic GM |
|---|---|---|---|---|---|---|
| Free | $0 | 30 (~10 short clips); BYOK unlimited | $0.39 | — | — | — |
| **Pro** | **$19/mo · $180/yr** | 600 | $7.80 | 59% | ~180 min | 88% |
| **Studio** (3 seats, +$25/seat) | **$79/mo · $790/yr** | 3,000 | $39.00 | 51% | ~1,200 min | 80% |
| **Scale / API** | **$299/mo** + $0.04/min overage | 12,000 | $156 | 48% | ~4,000 min | 83% |

Overage on Pro/Studio: $0.05/min (about 4× COGS). Hard-cap free at 30
min/month and keep BYOK: a BYOK user costs only FFmpeg and bandwidth, about
$0.004/run, and is the best free-tier design the product already has.

Full-use margin near 50% is intentional. Almost nobody consumes a metered
allowance fully; blended gross margin at any realistic mix lands at 75–85%.
Switching to `MEDIA_RESOLUTION_LOW` automatically above ~15 minutes improves
it further.

### Getting to $100k ARR

| Scenario | Pro @ $180/yr | Studio @ $790/yr | Scale @ $3,588/yr | ARR | Paying accounts |
|---|---|---|---|---|---|
| **A: team-led (recommended)** | 120 ($21.6k) | 90 ($71.1k) | 2 ($7.2k) | **$99.9k** | **212** |
| B: prosumer-led | 460 ($82.8k) | 25 ($19.8k) | 0 | $102.6k | 485 |
| C: API-led | 200 ($36.0k) | 6 ($4.7k) | 17 ($61.0k) | $101.7k | 223 |

Target Scenario A. 212 paying accounts over 12 months is ~18 net adds a
month. At 25% trial→paid conversion that is ~72 trials/month, which is
~1,500 monthly visitors at a 5% trial start rate. Reachable from SEO share
pages, MCP registries, the Play Store, and one good launch.

COGS at $100k ARR under Scenario A: ~130,000 min/month × $0.013 ≈ $1,690/mo,
plus ~$150/mo base infra (Railway API + worker + Redis + Postgres + object
storage) and ~3% Stripe fees. About $25k total cost, about $75k contribution.

## 2. Roadmap

### Phase 0: Foundation (weeks 1–4): identity and durable state

Nothing here is billable; all of it is prerequisite.

**Auth: Clerk.** `backend/app/infrastructure/auth/jwt_verifier.py` already
does exactly what Clerk needs (JWKS URL, issuer, audience, RS256), so the
backend change is three env vars, not code. Clerk gives Organizations (maps
1:1 to the Studio workspace tier), is free to 10k MAU, and has the best
Next.js App Router SDK. WorkOS is cheaper at 50k+ MAU, which is not a concern
yet. Supabase Auth would drag in a second platform.

The one constraint: `frontend/next.config.mjs` uses `output: "export"` for
the Capacitor build, so Clerk middleware cannot run there. Do auth entirely
client-side: `useSession()` → JWT → `Authorization: Bearer`. The same code
path then works in the web SPA, the PWA, and the APK. Do not adopt Clerk's
server-component patterns in this repo.

| Work | Layer | Files |
|---|---|---|
| `Principal` gains `account_id`, `workspace_id`, `plan`, `role` | backend domain | `domain/entities.py` |
| Map Clerk claims (`sub`, `org_id`, `org_role`) → `Principal` | backend interface | `interface/api/dependencies.py` |
| `AccountRepository`, `WorkspaceRepository` ports | backend domain | `domain/ports.py` |
| Postgres adapters + Alembic migrations | backend infra | new `infrastructure/persistence/postgres/{engine,accounts,workspaces,runs}.py` |
| `TieredRunRepository`: Redis for live state, Postgres as system of record | backend infra | new `infrastructure/persistence/tiered_run_repository.py`; satisfies the existing `RunRepository` Protocol so `process_run.py` is untouched |
| Wire both | backend | `container.py` |
| `AUTH_*`, `DATABASE_URL`, plan defaults | backend infra | `infrastructure/config.py` |
| `AuthSession` port + Clerk adapter + `useSession` hook; gateway attaches the bearer token | frontend | `domain/ports.ts`, new `infrastructure/clerkSession.ts`, new `application/useSession.ts`, `infrastructure/runsGateway.ts`, `infrastructure/container.ts` |
| Sign-in surface in nav | frontend | `components/AppNav.tsx`, new `components/panels/AccountPanel.tsx` |

**Keep Redis.** The 3-second poll in `useAnalysisRun` hits
`GET /api/runs/{id}` constantly; that stays Redis. Postgres gets a write on
create and on terminal status (`set_result` / `set_error`).
`TieredRunRepository` reads Redis first and falls back to Postgres on a miss,
which is also what lets paid history outlive `RUN_TTL_SECONDS` while the
free/anonymous path keeps its Redis-only 7-day behaviour, exactly as the
product direction in `CLAUDE.md` requires.

**Postgres schema** (Alembic; SQLAlchemy 2.0 async, because `asyncpg` alone
gives no migrations):

```
accounts(id, clerk_user_id uniq, email, created_at, default_workspace_id)
workspaces(id, name, owner_account_id, plan, seats,
           stripe_customer_id, stripe_subscription_id,
           minutes_included, minutes_used_period,
           period_start, period_end, max_duration_seconds, created_at)
workspace_members(workspace_id, account_id, role, PK(workspace_id, account_id))
runs(id uuid PK, workspace_id FK, created_by FK, status, stage,
     source_kind, source_url, platform, title, duration_seconds,
     completeness, error, created_at, updated_at, completed_at)
     -- idx (workspace_id, created_at DESC)
run_results(run_id PK FK, summary, transcript, screen_text, markdown,
            transcript_segments jsonb, screen_text_segments jsonb,
            source_metadata jsonb,
            search_tsv tsvector GENERATED)  -- GIN idx
usage_events(id, workspace_id, run_id, minutes_billed numeric,
             input_tokens, output_tokens, cost_estimate_usd,
             stripe_meter_event_id, created_at)
api_keys(id, workspace_id, name, prefix, hash, scopes jsonb,
         last_used_at, revoked_at, created_at)
shared_pages(slug PK, run_id FK, workspace_id FK, visibility,
             view_count, created_at)
```

### Phase 1: Monetizable (weeks 5–9): the first dollar

**Billing: Stripe Checkout + Billing.** Subscription price per seat plus a
Stripe Meter for overage minutes. Not usage-only pricing (unpredictable for
the buyer, impossible to forecast ARR from). Not Paddle unless
merchant-of-record VAT handling is needed; revisit at $50k ARR.

| Work | Layer | Files |
|---|---|---|
| `BillingGateway`, `UsageMeter` ports | backend domain | `domain/ports.py` |
| Stripe adapter (checkout session, portal, meter events, webhook signature) | backend infra | new `infrastructure/billing/stripe_gateway.py` |
| Entitlement resolution (plan → minutes, max duration, rate limit, concurrency) | backend domain + application | new `domain/entitlements.py`, new `application/resolve_entitlement.py` |
| `StartCheckoutUseCase`, `SyncSubscriptionUseCase`, `RecordUsageUseCase` | backend application | new files under `application/` |
| `CreateRunUseCase` checks the meter, not only `SpendCap` | backend application | `application/create_run.py` (the `spend_cap.try_consume()` branch becomes plan-aware; `SpendCap` survives for anonymous) |
| Record token usage after analysis | backend application | `application/process_run.py`, `UsageMeter.record(...)` after `set_result` |
| Return token counts from Gemini | backend infra | `infrastructure/ai/gemini_engine.py`: read `response.usage_metadata` |
| Routes: `POST /api/billing/checkout`, `POST /api/billing/portal`, `POST /api/webhooks/stripe` | backend interface | `interface/api/routes.py` (webhook needs the raw body and bypasses `get_principal`) |
| Upgrade/usage UI | frontend | new `application/useBilling.ts`, new `components/panels/BillingPanel.tsx`, `components/AppNav.tsx` |

**Lifting the 3-minute limit.** `max_duration_seconds` moves from `Settings`
to the entitlement. Three consequences:

1. `MediaProcessor.enforce_duration_cap(run_id, path)` gains a `max_seconds`
   parameter. That is a Protocol change in `domain/ports.py` touching
   `infrastructure/media/{service,ffmpeg}.py`, `application/{create_run,
   process_run}.py`, and their tests.
2. **Media resolution by duration.** Above ~15 min pass
   `media_resolution=MEDIA_RESOLUTION_LOW` in `GenerateContentConfig`. Three
   times fewer tokens, and for talking-head and tutorial content the
   on-screen-text quality holds. Above 45 min it is not optional.
3. **Chunking above ~45 minutes.** Build it as a decorator adapter, not a use
   case: `ChunkedGeminiEngine(GeminiEngine)` satisfying the same
   `AnalysisEngine` Protocol, selected in `container.py`. It segments with
   FFmpeg into ≤20-min parts, analyzes each, offsets every segment's
   timestamps by the chunk start, concatenates transcript/screen text/
   segments, then runs one text-only reduce pass over the merged transcript
   for a single title/summary/notes. `ProcessRunUseCase` does not change,
   which is the payoff of the existing layering.

Also raise `WORKER_JOB_TIMEOUT_SECONDS` (600 s will not survive a 2-hour
video) and give paid runs their own arq queue so a Studio customer's
hour-long upload does not block the free tier.

**MCP server (`mcp/`): build it.**

- Node/TypeScript, stdio transport, published as `@videolens/mcp`, run via
  `npx -y @videolens/mcp`. Thin REST client over the existing API, as
  `CLAUDE.md` already describes; no shared use-case code with the backend.
- Auth: `VIDEOLENS_API_KEY` from `process.env` (workspace-scoped, counts
  against plan minutes) **or** `GEMINI_API_KEY` for BYOK free use. Never a
  tool argument, never a file. Keep the `~/.videolens/client_id` dotfile for
  the anonymous BYOK path only.
- Tools: `analyze_video({ url?, file_path?, wait_seconds? })` (blocks on the
  poll, returns the parsed result plus `share_url`), `get_run({ run_id })`,
  `list_recent_runs({ limit })`, `search_library({ query, platform?,
  since? })` (the tool that makes the server sticky: an agent can grep every
  video you have ever analyzed), `export_run({ run_id, format })`.
- Also ship a **remote HTTP MCP endpoint** (`POST /mcp`, streamable HTTP, API
  key as bearer) as a FastAPI route in `interface/api/`. That is what gets
  the product into Claude Desktop and web connector directories with nothing
  to install, and it is ~150 lines because the endpoints already exist.

**Public API + API keys.** `POST /api/keys`, `GET /api/keys`,
`DELETE /api/keys/{id}`. Store `prefix` (`vl_live_a1b2`) plus a SHA-256
hash; show the full key once. `get_principal` in
`interface/api/dependencies.py` gains a branch before the JWT branch: a
bearer starting with `vl_` resolves to a workspace `Principal`.
`quota_key_from_headers` in `domain/policies.py` already hashes bearer
tokens for rate limiting, so that keeps working unchanged.

**Library + search.** `GET /api/runs?query=&platform=&from=&to=&cursor=`
against the `search_tsv` GIN index, `ts_rank` ordering, keyset pagination.
Frontend: a fifth tab. New `LibraryGateway` port in `frontend/domain/ports.ts`,
adapter in `infrastructure/`, `application/useLibrary.ts`,
`components/panels/LibraryPanel.tsx`, added to `MAIN_TABS` in
`application/useMainTab.ts` and to `AppNav.tsx`. The existing `HistoryPanel`
becomes the free-tier view; Library is the paid one.

### Phase 2: Growth (weeks 10–16)

**Public share pages: the single highest-leverage growth feature.** Every
analysis becomes an indexable page at `/v/{slug}` with the title, summary,
timestamped transcript, on-screen text, and notes. Long-tail SEO ("what does
X say in Y video") plus a viral loop off the existing copy/share affordances
in `ResultsView.tsx`.

The web build is already `standalone`, so add `frontend/app/v/[slug]/page.tsx`
as a server component with `generateMetadata` (OG tags) fetching
`GET /api/public/runs/{slug}`. Gate the route out of the Capacitor export
build. Backend: `shared_pages` table, `POST /api/runs/{id}/share`,
unauthenticated `GET /api/public/runs/{slug}`, and a sitemap feed. Free-tier
share pages carry an "Analyzed with VideoLens" footer; Pro can turn it off.

**Exports.** In order of value per effort: Markdown + JSON + SRT/VTT download
(`buildMarkdownReport` in `ResultsView.tsx` is most of it) → Obsidian (a
`.md` with frontmatter, zero OAuth) → Notion (OAuth, `export_connections`
table, `infrastructure/exports/notion.py` behind a new `ExportTarget` port)
→ Readwise → Zapier/n8n via webhooks. Cut Readwise and Zapier from year one
unless a customer asks by name.

**Chrome extension, and it is not only growth.** A MV3 extension that
captures media from the user's *own authenticated browser session* and
uploads the file to `POST /api/runs`. This is the strategic answer to the
yt-dlp problem below: the download happens on the user's machine under their
own session, and the servers never touch a platform's media endpoint. It also
gives a one-click "analyze this Reel" button inside the sites the primary
customer lives in all day.

**Play Store.** The APK already builds in CI. The listing is a week of
compliance paperwork (data safety form, privacy policy, content rating,
closed testing track). Worth doing for distribution credibility, and
share-sheet intake is the best mobile capture UX in this category. Not before
there are paying customers.

### Phase 3: Scale (month 5+)

Teams/workspaces (`workspace_members` is already in the schema; add invites,
roles, seat-quantity sync to Stripe), collections/boards (the teardown board
the primary customer actually wants), saved searches, batch URL intake
(paste 50 links), webhooks on run completion, SSO via Clerk enterprise
connections, and a second `AnalysisEngine` adapter for model diversification.

## 3. Risks, and what to cut

**yt-dlp and platform terms of service: the biggest risk, and it must be
handled before charging money.** Today the resolver chain in
`infrastructure/media/resolvers/` downloads from Instagram/TikTok/YouTube
server-side, and `YTDLP_COOKIES_FILE` exists to authenticate against
login-gated sources. Doing that for free anonymous users is one exposure
profile. Doing it as a paid, advertised feature, at volume, from a known
datacenter IP is another: YouTube's terms forbid it explicitly, and the
project becomes a commercial target instead of a hobby. `DEPLOYMENT.md`'s
"do not advertise support for every social-media URL" is the right instinct.
Formalize it:

1. Never run a server-side cookie jar for platform accounts in the paid
   deployment. It is the single thing most likely to get an account banned
   and a legal letter sent.
2. Make the paid happy path device-side capture: file upload, the Chrome
   extension, and the Android share sheet. Market those.
3. Keep server-side URL fetch as an undocumented, best-effort, no-SLA
   convenience with its own rate limit, and keep the caption-salvage path in
   `process_run.py` as the graceful degradation it already is.
4. Terms already require a media-permission and copyright acknowledgement
   (`accept_terms`). Keep it, log it per run, and add DMCA agent details
   before taking payment.

**AGPL-3.0: keep it.** Do not relicense to BSL and do not go open-core by
withholding: the open repo and the MCP server *are* the distribution channel,
and a solo developer cannot afford another. AGPL costs nothing here: the
copyright holder's own hosted service is unconstrained, and §13's network-use
clause deters a competitor from SaaS-ifying the code. Two additions:
**(a)** require a CLA (CLA Assistant, about an hour of setup) on every
external contribution to retain the right to dual-license later. Without it
the first accepted outside PR permanently forecloses an enterprise on-prem
license. **(b)** keep proprietary assets (brand, Play listing, any paid-only
prompt tuning) out of the licensed tree so the boundary is unambiguous.

**Gemini single-vendor dependency.** A deprecation, price change, or regional
outage takes the product down; `AnalysisEngineProbe` will report it and that
is all. Mitigations in order of cost: record `input_tokens`/`output_tokens`
per run from day one (`usage_events`) so a price change can be modelled
instantly; make `gemini_model` per-plan rather than global; and rely on
`AnalysisEngine` already being a Protocol, so a second adapter is a drop-in
at `container.py`. Do not build the second adapter in year one. Just do not
let anything outside `infrastructure/ai/` learn Gemini-specific vocabulary.

**Solo-developer bandwidth: the constraint that shapes everything.**
Realistic capacity is ~20 focused hours a week. The repo shows ~16 commits
over three months, a hobby cadence; the plan below assumes roughly tripling
it.

**Ship in 90 days:** Clerk auth, Postgres + Alembic + tiered repository,
Stripe subscriptions + entitlements, per-plan duration limits with
`MEDIA_RESOLUTION_LOW`, library + search, API keys, the MCP server (stdio +
remote), public share pages.

**Do not ship in 90 days:** teams/invites/SSO, Notion/Readwise OAuth, the
Chrome extension, chunked >45-min analysis, Play Store, a frontend test
runner, a second AI vendor, SOC 2, a marketing site beyond one landing page.

**Cut permanently unless a paying customer asks by name:** Readwise, Zapier,
real-time collaboration, video editing/clipping, speaker diarization beyond
what Gemini already returns, on-prem/self-host support tiers, and any attempt
to support "every platform". Also resist fixing the six pre-existing ESLint
errors or adding a frontend test suite before revenue; they are documented,
understood, and not costing customers.

## 4. The 90-day execution plan

Two-week sprints. The goal of the first six weeks is one thing only: **a
stranger can pay you.**

| Sprint | Weeks (from 2026-09-15) | Ship | Definition of done |
|---|---|---|---|
| **S1** | 1–2 | Clerk auth end-to-end; `Principal` carries account + workspace; Postgres + Alembic + `accounts`/`workspaces`/`runs`/`run_results`; `TieredRunRepository` | A signed-in run persists past `RUN_TTL_SECONDS`; anonymous path unchanged; backend tests green |
| **S2** | 3–4 | Entitlements; `UsageMeter` + `usage_events` with real token counts; per-plan `max_duration_seconds` (Protocol change through `ffmpeg.py`); `MEDIA_RESOLUTION_LOW` above 15 min | A "pro" flag on a workspace lets a 20-min video through and records minutes + cost |
| **S3** | 5–6 | **Stripe Checkout + portal + webhooks; pricing page; upgrade flow.** Pro $19 / Studio $79 live | **First paying customer.** Charge someone you already know. Hand-onboard them. |
| **S4** | 7–8 | Library tab + Postgres FTS; API keys; public REST docs | A Studio user can search 200 past runs by on-screen text in <300 ms |
| **S5** | 9–10 | **MCP server** (`mcp/`, npm-published, stdio) + remote `/mcp` endpoint; submit to MCP registries | `npx -y @videolens/mcp` works from a clean machine with an API key |
| **S6** | 11–12 | Public share pages (`/v/{slug}`), OG cards, sitemap; Markdown/JSON/SRT export; landing page rewritten around the screen-text wedge | 50 share pages indexed; every result has a one-click public link |
| **S7** | 13 (buffer) | Launch: Product Hunt, r/marketing, r/ClaudeAI, one UGC-agency community; fix what S1–S6 broke | 10 paying accounts |

**Sequencing rule:** every sprint ends with something deployed to production
on `main`. The existing CI (PR checks → `dev` → `main` publishes GHCR + APK)
already enforces this.

**Do S3 before S4.** The instinct will be to make the product better before
charging. Resist it. Stripe on top of a 3-minute-limited tool with no library
still closes a customer who has the pain, and the first invoice teaches more
than the next month of building.

**Metrics: five, checked weekly, nothing else.**

| Metric | Source | 90-day target |
|---|---|---|
| Paying workspaces | `workspaces.plan != 'free'` | 10 |
| MRR / ARR | Stripe | $500 MRR |
| Activation: signup → first completed run within 24 h | `runs` joined to `accounts` | >60% |
| Week-4 retention of paying workspaces (≥1 analysis) | `runs` by `workspace_id`, weekly buckets | >70% |
| Gross margin: `sum(usage_events.cost_estimate_usd)` ÷ Stripe revenue | Postgres + Stripe | COGS <30% of revenue |

Two operational alarms, not metrics: **run success rate by source kind**
(upload vs URL vs caption-salvage; this is the yt-dlp health signal and it
degrades without warning) and **p95 time-to-result by duration bucket**.

**Months 4–6, if the 90 days land:** teams/invites, Chrome extension (which
doubles as the ToS mitigation), chunked long-form, Notion export, Play Store.
**Months 7–12:** the SEO flywheel compounding off share pages, one outbound
push into UGC agencies, the Scale/API tier, and the CLA-enabled enterprise
on-prem conversation. That is the path from $500 MRR to ~$8.3k MRR.

## Critical files for implementation

- `backend/app/domain/ports.py`: every new capability (Postgres repo,
  `UsageMeter`, `BillingGateway`, `AccountRepository`, chunked engine) enters
  through a Protocol here. `MediaProcessor.enforce_duration_cap` is the one
  existing signature that must change.
- `backend/app/container.py`: the composition root that selects
  `TieredRunRepository`, `ChunkedGeminiEngine`, the Stripe adapter, and the
  entitlement use case. Nothing else in the backend needs to know they exist.
- `backend/app/application/create_run.py`: where the free `SpendCap` check
  becomes a plan-aware `UsageMeter` allowance check and per-plan duration
  limits are enforced at intake.
- `backend/app/interface/api/dependencies.py`: `get_principal` grows from two
  branches (JWT / `X-Client-ID`) to four (API key `vl_*`, Clerk JWT with
  `org_id`, anonymous client ID, rejected). The chokepoint for every
  authorization decision.
- `backend/app/infrastructure/ai/gemini_engine.py`: media resolution by
  duration, `usage_metadata` extraction for metering, and the base the
  chunking decorator wraps.
- `frontend/infrastructure/runsGateway.ts` + `frontend/infrastructure/container.ts`:
  the single place the client learns to send a Clerk bearer token alongside
  the existing `X-Client-ID` / `X-Gemini-Api-Key` headers.

## Changelog

- 2026-09-15 · main session (plan drafted by an Opus planning subagent, verified against source) · initial plan
