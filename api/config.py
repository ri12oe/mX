from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_KEY_LENGTH = 32


class Settings(BaseSettings):
    """App settings, loaded from environment variables or .env."""

    # hide_input_in_errors: a rejected key is never echoed in the error message.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    mx_api_key: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    primary_provider: str = "anthropic"
    primary_model: str = "claude-sonnet-5-5"
    database_url: str = "sqlite:///./mx.db"

    @field_validator("mx_api_key")
    @classmethod
    def _key_must_be_strong(cls, value: str) -> str:
        """Refuse to start with a missing, placeholder, or short API key."""
        if not value or value.startswith("change-me") or len(value) < MIN_KEY_LENGTH:
            raise ValueError(
                f"MX_API_KEY must be a random string of at least {MIN_KEY_LENGTH} characters, "
                "not empty or the change-me placeholder. Generate one with: "
                'python -c "import secrets; print(secrets.token_urlsafe(32))"'
            )
        return value


settings = Settings()
