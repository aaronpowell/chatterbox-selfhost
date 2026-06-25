from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "chatterbox-selfhost"
    app_env: str = "dev"
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    database_url: str = "sqlite:///./data/app.db"
    redis_url: str = "redis://localhost:6379/0"

    audio_storage_path: str = "./audio"
    model_storage_path: str = "./models"
    job_storage_path: str = "./data/jobs"

    enable_auth: bool = False
    api_key: str = ""


settings = Settings()

