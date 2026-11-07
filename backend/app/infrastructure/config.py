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

    max_file_size_mb: int = 200
    max_duration_seconds: int = 180
    rate_limit_per_hour: int = 20
    # Per-IP limit on the read endpoints (run polling, run list, free-run
    # status). Generous: the web app polls one run every 3 s. <= 0 disables.
    read_rate_limit_per_minute: int = 120
    # How many trailing X-Forwarded-For entries the deployment's own proxies
    # append. The client IP is the entry that many from the END of the header;
    # anything further left was supplied by the client and is not trusted.
    # 1 for Railway and most single-edge platforms; 0 = ignore the header and
    # use the socket peer (service reached directly, no proxy).
    trusted_proxy_hops: int = 1
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

    auth_jwks_url: str = ""
    auth_issuer: str = ""
    auth_audience: str = ""
    allow_anonymous: bool = True

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
