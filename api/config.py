from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App settings, loaded from environment variables or .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mx_api_key: str = "change-me"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    primary_provider: str = "anthropic"
    primary_model: str = "claude-sonnet-5-5"
    database_url: str = "sqlite:///./mx.db"


settings = Settings()
