from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    max_file_size_mb: int = 200
    max_duration_seconds: int = 180
    rate_limit_per_hour: int = 10

    temp_dir: str = "/tmp/videolens"
    allowed_origins: str = "*"

    allowed_extensions: tuple[str, ...] = (".mp4", ".mov")


settings = Settings()
