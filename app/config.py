from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "chatterbox-selfhost"
    app_env: str = "dev"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = Field(default="INFO", validation_alias=AliasChoices("LOG_LEVEL", "APP_LOG_LEVEL"))

    database_url: str = "sqlite:///./data/app.db"
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        validation_alias=AliasChoices("REDIS_URL", "REDIS_URI", "ConnectionStrings__redis"),
    )
    enable_tracing: bool = True
    otlp_endpoint: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OTEL_EXPORTER_OTLP_ENDPOINT", "OBSERVABILITY_OTLP_ENDPOINT"),
    )
    seq_uri: str | None = Field(default=None, validation_alias=AliasChoices("SEQ_URI"))

    audio_storage_path: str = "./audio"
    model_storage_path: str = "./models"
    job_storage_path: str = "./data/jobs"

    enable_auth: bool = False
    api_key: str = ""


settings = Settings()
