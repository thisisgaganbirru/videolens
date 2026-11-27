from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# The Capacitor Android WebView serves the bundled Next.js export from the
# APK itself, under the hostname "localhost" - nothing is listening on a
# port, no traffic leaves the device, it is just the naming scheme Chrome
# uses to identify the page it is rendering. That makes every API call
# cross-origin, stamped with this as the `Origin` header.
#
# Unlike a deployed frontend's origin, these are fixed constants of the
# native shell rather than a per-deployment detail, so they belong in code
# instead of `ALLOWED_ORIGINS`. Leaving them to configuration means every
# new environment ships an APK that silently fails its CORS preflight with
# a 400, which `fetch` cannot distinguish from an offline server - the app
# just says "Can't reach the server."
#
# `https` is Capacitor's default `androidScheme`; `http` covers a config
# that overrides it. Both are the app talking to its own backend, which is
# why they are allowed unconditionally.
NATIVE_APP_ORIGINS = ("https://localhost", "http://localhost")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.6-flash"
    # Tried with the already-uploaded file once the primary model has exhausted
    # its transient (429/5xx) retries. Blank = primary only.
    gemini_fallback_model: str = ""
    # Total generate_content attempts on the primary model for 429/5xx, with
    # full-jitter exponential backoff (2s base, doubling) between them.
    gemini_retry_attempts: int = 6
    gemini_retry_max_delay_seconds: float = 20.0
    # Per-part media resolution for the image slides of a multi-slide post.
    # Gemini 3's default for an image is `high` (about 1120 tokens), which
    # read a slide's headline but dropped its small print; `ultra_high`
    # (about 2240, per part only) is the one level above it. Blank = leave it
    # to the model's default. Videos and single files never carry one.
    gemini_slide_image_resolution: Literal["", "low", "medium", "high", "ultra_high"] = "ultra_high"

    max_file_size_mb: int = 200
    max_duration_seconds: int = 180
    # The bigger set for a caller who is signed in (JWT or account API key)
    # AND brings their own Gemini key on the run. Everyone else gets the two
    # above. A value at or below the standard one means the standard one:
    # this tier can only ever be bigger (application/entitlements.py).
    signed_in_byok_max_duration_seconds: int = 600
    signed_in_byok_max_file_size_mb: int = 500
    rate_limit_per_hour: int = 20
    # Per-IP limit on the read endpoints (run polling, run list, free-run
    # status). Generous: the web app polls one run every 3 s. <= 0 disables.
    read_rate_limit_per_minute: int = 120
    # Where the client sits in X-Forwarded-For, counted from the END: the
    # client IP is the entry this many from the right, i.e. the number of
    # trailing entries the deployment's own proxies write. Anything further
    # left came from the client and is not trusted. 2 for Railway: its edge
    # replaces the header with "<client>, <edge hop>", and the edge hop varies
    # per request (measured 2026-11-07), so 1 keyed every request on a
    # different address. 1 for a platform whose proxy appends just the client;
    # 0 = ignore the header and use the socket peer (no proxy). Without the
    # header (local, docker compose, direct) the socket peer is used anyway.
    trusted_proxy_hops: int = 2
    # Failed credentials (unknown API key, bearer token that does not
    # verify) one client IP may send per 15-minute window. Past it, every
    # request from that IP carrying a credential is a 429 before any key
    # lookup or token check. Successful requests are never counted. <= 0
    # disables.
    auth_failure_limit_per_ip: int = 30
    daily_run_cap: int = 200
    # Free runs per device per UTC day for callers without their own Gemini
    # key. <= 0 turns the free-run allowance off entirely (no device token
    # needed, no limit beyond DAILY_RUN_CAP).
    free_runs_per_device: int = 3
    # Backstop for the above, per client IP per UTC day: clearing browser
    # storage mints a new device, not a new IP. Set above the device limit
    # because shared networks (offices, campuses, carrier NAT) put many
    # people behind one IP. <= 0 disables the IP backstop only.
    free_runs_per_ip: int = 10
    # Free runs per signed-in account per UTC day, for callers without their
    # own Gemini key (owner decision 2026-11-14; it was 10 per month, which
    # gave a signed-in person less than an anonymous device's 3 a day).
    # Counted against the account (so they follow the person across devices)
    # INSTEAD of the device counter, not on top of it. Needs an account store
    # (DATABASE_URL, or the in-memory one in local mode). <= 0 turns it off:
    # signed-in callers then fall back to the device rule above. Replaces
    # FREE_RUNS_PER_ACCOUNT_MONTHLY, which is no longer read.
    free_runs_per_account_daily: int = 10
    # HMAC key for device tokens. Required in distributed mode (REDIS_URL
    # set) while free runs are on, or replicas would reject each other's
    # tokens; generated per process (with a warning) in local mode.
    device_token_secret: str = ""
    # 1 hour. The browser keeps History (IndexedDB) now; the server only holds
    # a run until it has been delivered. Re-armed on every write, so the hour
    # counts from completion. Also bounds what GET /api/runs (and the MCP
    # server's list_recent_runs) can still see.
    run_ttl_seconds: int = 3600
    worker_max_jobs: int = 2
    worker_job_timeout_seconds: int = 600
    # arq timeout for runs admitted under the signed-in + BYOK limits (a
    # separate job function, `process_long_run`), whose media can be ~3x
    # longer: download + FFmpeg re-encode + Gemini upload/processing of a
    # 10-minute video does not fit in 600 s on a small worker. Standard runs
    # keep WORKER_JOB_TIMEOUT_SECONDS. Never below it.
    worker_long_job_timeout_seconds: int = 1800
    # Seconds a worker given SIGTERM (a deploy) keeps running its in-flight
    # jobs before cancelling them; it takes no new ones meanwhile (arq's
    # `job_completion_wait`). 0 = cancel at once. A cancelled job is re-queued
    # and its run resumes on the next worker, so this only saves the work
    # already done. Must stay a few seconds UNDER the platform's stop grace
    # period (Railway: the service's draining time; check it on the
    # dashboard): a worker killed mid-wait leaves its jobs locked for the
    # whole job timeout, and the read-time stale check fails them first.
    worker_job_completion_wait_seconds: int = 0
    # Total wall-clock time a run's link downloading may take, however the
    # server paces its bytes: every route together (yt-dlp, the plain-file
    # fallback, then the caption fallback) share this one budget. Keep it
    # well under WORKER_JOB_TIMEOUT_SECONDS: the job still has to re-encode
    # and analyze afterwards.
    download_deadline_seconds: int = 300

    temp_dir: str = "/tmp/videolens"
    allowed_origins: str = "http://localhost:3000,http://localhost:3005"
    redis_url: str = ""

    s3_endpoint_url: str = ""
    s3_region: str = "auto"
    s3_bucket: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    # "auto" lets botocore pick, which with a custom endpoint means path-style
    # (https://endpoint/bucket) - what MinIO in docker-compose needs. Railway
    # Buckets created after Railway's switch want virtual-hosted style
    # (https://bucket.endpoint); older ones still want "path". The bucket's
    # Credentials tab says which, and the wrong one fails HeadBucket with 403.
    s3_addressing_style: str = "auto"

    # OIDC token verification (Supabase Auth in practice; see .env.example).
    # JWKS URL and issuer make a token verifiable at all and are both
    # required; the audience is enforced whenever it is set.
    auth_jwks_url: str = ""
    auth_issuer: str = ""
    auth_audience: str = ""
    allow_anonymous: bool = True

    # Accounts, workspaces, members and API keys. Blank = no database: the
    # API keeps those in process memory in local mode, and has no account
    # store at all in distributed mode (signed-in callers are bare subjects,
    # key management answers 503). Postgres URLs (postgres://, postgresql://)
    # are rewritten for asyncpg; sqlite+aiosqlite:/// works for local use.
    # The schema is Alembic's (`alembic upgrade head`), run as a release step.
    database_url: str = ""
    # Postgres connection pool per process (API and worker each have one).
    # On the Supabase session pooler every open connection holds a real
    # server connection, so (pool size + overflow) x processes must stay
    # under the pooler's session limit for the project's plan, which is
    # read from the dashboard (DEPLOYMENT.md, "Database connections").
    # SQLAlchemy's own defaults; SQLite ignores both.
    database_pool_size: int = 5
    database_max_overflow: int = 10
    # Live API keys a workspace may hold at once.
    api_keys_per_workspace: int = 10

    # The paid plan (docs/backend/billing.md). Billing is on only when the
    # secret key, the webhook secret, the monthly price and the extra-run
    # price are all set; blank any of them and everything behaves as it did
    # before billing existed. Test-mode keys (`sk_test_`) for all work until
    # the owner says otherwise. Amounts live in the Stripe Prices, never here.
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    # Recurring licensed prices of the one plan. Yearly is optional: blank =
    # monthly only (`prices.year` null, a yearly checkout is a 400).
    stripe_price_monthly: str = ""
    stripe_price_yearly: str = ""
    # The per-extra-run price: recurring, monthly, usage_type=metered, tied
    # to the Billing Meter below. Rides on every subscription, the yearly
    # one included (a mixed-interval subscription, flexible billing mode).
    stripe_price_extra_run: str = ""
    # Optional yearly metered price on the same meter. Set it and yearly
    # subscribers carry it instead, billed once a year in arrears, for a
    # Stripe account where mixed intervals are not available.
    stripe_price_extra_run_yearly: str = ""
    # The Billing Meter's `event_name`.
    stripe_meter_event_name: str = "videolens_extra_run"
    # Where Checkout and the Customer Portal send the person back. Blank =
    # the first ALLOWED_ORIGINS entry. Paths are fixed:
    # /app?view=account&billing=success|cancel.
    billing_return_origin: str = ""
    # Shared-key runs included per UTC day on the paid plan (owner decision
    # 2026-11-14: 30 a day; it was PAID_RUNS_PER_MONTH=100, which is no
    # longer read). Counted on the account's daily row, the same one the
    # free plan uses. Runs past it are extra runs, billed after success.
    paid_runs_per_day: int = 30
    # Media limits on the paid plan, with or without the person's own key.
    # <= 0 = the SIGNED_IN_BYOK_* values; never below the standard limits.
    paid_max_duration_seconds: int = 0
    paid_max_file_size_mb: int = 0
    # Safety net on extra runs per account per UTC month: past it a paid run
    # is refused (402 extra_runs_cap) instead of growing the bill. <= 0 = no cap.
    paid_extra_runs_monthly_cap: int = 200
    # Saved history (docs/backend/saved-history.md). A paid account's run
    # results are saved on the server; once its paid plan ends they stay
    # readable and deletable this many days, then are removed for good.
    paid_saved_runs_grace_days: int = 30
    # Largest result one saved run may store, in bytes of JSON. Over it the
    # segment lists are dropped first; a result still over it is not saved
    # (logged). A 10-minute run is tens of KB, so normal runs never hit it.
    paid_saved_run_max_bytes: int = 2 * 1024 * 1024
    # DELETE /api/me holds the account this many days (it stops working at
    # once; the person can sign in and restore it), then the worker's
    # cleanup removes it, its saved runs and its Supabase user for good.
    account_deletion_hold_days: int = 30

    github_repo: str = "thisisgaganbirru/videolens"
    github_token: str = ""

    ytdlp_cookies_file: str = ""
    ytdlp_cookies_from_browser: str = ""
    # Tallest video yt-dlp fetches for a URL run. A soft cap via yt-dlp's
    # format_sort "res:N": the largest variant at or under N wins, and a source
    # with nothing that small falls back to its smallest variant rather than
    # failing. FFmpeg re-encodes everything anyway and Gemini doesn't need more
    # than 720p, so a bigger download only costs time, memory and exposure to
    # mid-download 403s. <= 0 removes the cap (yt-dlp's own "best").
    ytdlp_max_height: int = 720
    ffmpeg_location: str = ""

    allowed_extensions: tuple[str, ...] = (".mp3", ".mp4", ".mov")

    @property
    def allowed_origin_list(self) -> list[str]:
        configured = [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]
        return configured + [o for o in NATIVE_APP_ORIGINS if o not in configured]

    def distributed_origin_error(self) -> str | None:
        """Why this configuration must not start, or None.

        A distributed deployment (REDIS_URL set) is a deployed one, and a CORS
        wildcard there lets any website call the API from a browser. Refused
        at startup rather than warned about: a warning in a platform log is
        read by nobody until it matters.
        """
        if not self.queue_enabled:
            return None
        if any(origin.strip() == "*" for origin in self.allowed_origins.split(",")):
            return (
                "ALLOWED_ORIGINS is \"*\" in a distributed deployment (REDIS_URL is set). "
                "Any website could call this API from a browser. Set ALLOWED_ORIGINS to the "
                "real frontend origin(s)."
            )
        return None

    def startup_error(self, role: str) -> str | None:
        """The first configuration rule this process breaks, or None. One
        list for both entry points (`interface/startup.py`), so the API and
        the worker cannot drift: `role` is "api" or "worker", and only the
        CORS rule is the API's alone (the worker answers no browser)."""
        checks = [self.distributed_database_error, self.distributed_billing_error]
        if role == "api":
            checks.insert(0, self.distributed_origin_error)
        for check in checks:
            error = check()
            if error:
                return error
        return None

    def distributed_database_error(self) -> str | None:
        """Why this database configuration must not start, or None.

        SQLite is a file on one machine, so each replica of a distributed
        deployment would hold its own accounts and API keys, and a key minted
        on one would 401 on the next. Same reasoning as leaving the account
        store disabled, rather than in-memory, when `DATABASE_URL` is blank.
        """
        if not self.queue_enabled:
            return None
        if self.database_url.strip().lower().startswith("sqlite"):
            return (
                "DATABASE_URL is a SQLite URL in a distributed deployment (REDIS_URL is set). "
                "Each replica would keep its own accounts and API keys. Use the Postgres "
                "(Supabase) URL, or leave DATABASE_URL blank."
            )
        return None

    @property
    def billing_configured(self) -> bool:
        """Every required STRIPE_* setting is present."""
        return all(
            value.strip()
            for value in (
                self.stripe_secret_key,
                self.stripe_webhook_secret,
                self.stripe_price_monthly,
                self.stripe_price_extra_run,
                self.stripe_meter_event_name,
            )
        )

    @property
    def billing_return_base(self) -> str:
        """The origin Checkout and the portal return to, without a slash."""
        configured = self.billing_return_origin.strip()
        if not configured:
            configured = next(
                (o.strip() for o in self.allowed_origins.split(",") if o.strip() and o.strip() != "*"),
                "http://localhost:3005",
            )
        return configured.rstrip("/")

    def distributed_billing_error(self) -> str | None:
        """Why this billing configuration must not start, or None. Without a
        database a distributed deployment has no account store, so there is
        no account to hang a subscription on, and a webhook would be dropped."""
        if not self.queue_enabled or not self.billing_configured:
            return None
        if not self.database_url.strip():
            return (
                "Billing is configured (STRIPE_*) in a distributed deployment (REDIS_URL is set) "
                "without DATABASE_URL. Subscriptions need the account store. Set DATABASE_URL, or "
                "blank STRIPE_SECRET_KEY to turn billing off."
            )
        return None

    @property
    def long_job_timeout_seconds(self) -> int:
        """WORKER_LONG_JOB_TIMEOUT_SECONDS, floored at the standard timeout."""
        return max(self.worker_long_job_timeout_seconds, self.worker_job_timeout_seconds)

    @property
    def queue_enabled(self) -> bool:
        return bool(self.redis_url.strip())

    @property
    def object_storage_enabled(self) -> bool:
        return all(
            value.strip()
            for value in (
                self.s3_endpoint_url,
                self.s3_bucket,
                self.s3_access_key_id,
                self.s3_secret_access_key,
            )
        )


settings = Settings()
