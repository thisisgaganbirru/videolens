from pydantic_settings import BaseSettings, SettingsConfigDict


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
    allowed_origins: str = "*"
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

    ytdlp_cookies_file: str = ""
    ytdlp_cookies_from_browser: str = ""
    ffmpeg_location: str = ""

    allowed_extensions: tuple[str, ...] = (".mp3", ".mp4", ".mov")

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
