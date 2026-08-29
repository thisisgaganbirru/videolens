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

    max_file_size_mb: int = 200
    max_duration_seconds: int = 180
    rate_limit_per_hour: int = 20
    daily_run_cap: int = 200
    run_ttl_seconds: int = 604800  # 7 days - drives both run TTL and history retention
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

    auth_jwks_url: str = ""
    auth_issuer: str = ""
    auth_audience: str = ""
    allow_anonymous: bool = True

    github_repo: str = "thisisgaganbirru/videolens"
    github_token: str = ""

    ytdlp_cookies_file: str = ""
    ytdlp_cookies_from_browser: str = ""
    ffmpeg_location: str = ""

    allowed_extensions: tuple[str, ...] = (".mp3", ".mp4", ".mov")

    @property
    def allowed_origin_list(self) -> list[str]:
        configured = [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]
        return configured + [o for o in NATIVE_APP_ORIGINS if o not in configured]

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
