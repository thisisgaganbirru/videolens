from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.6-flash"

    max_file_size_mb: int = 200
    max_duration_seconds: int = 180
    rate_limit_per_hour: int = 20
    run_ttl_seconds: int = 3600

    temp_dir: str = "/tmp/videolens"
    allowed_origins: str = "*"

    ytdlp_cookies_file: str = ""
    ytdlp_cookies_from_browser: str = ""
    ffmpeg_location: str = ""

    allowed_extensions: tuple[str, ...] = (".mp3", ".mp4", ".mov")


settings = Settings()
