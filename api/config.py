from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_KEY_LENGTH = 32
MIN_PASSWORD_LENGTH = 12


class Settings(BaseSettings):
    """App settings, loaded from environment variables or .env."""

    # hide_input_in_errors: a rejected key or password is never echoed in the error message.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    mx_api_key: str = ""  # for scripts and clients (X-mX-Key header); also signs session cookies
    mx_password: str = ""  # for the web login page
    anthropic_api_key: str = ""
    primary_provider: str = "anthropic"
    primary_model: str = "claude-opus-5-5"
    db_path: str = "./data/mx.db"
    system_prompt_file: str = "prompts/mx_system_v3.md"
    # Built React app, served at / when present (the Docker image builds it).
    web_dist: str = "web/dist"
    # Session cookies are HTTPS-only. Browsers still accept them on http://localhost.
    cookie_secure: bool = True
    # Browser origins allowed to call the API from elsewhere. In .env, write as JSON.
    cors_origins: list[str] = ["http://localhost:5173"]

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

    @field_validator("mx_password")
    @classmethod
    def _password_must_be_set(cls, value: str) -> str:
        """Refuse to start without a real web login password."""
        if len(value) < MIN_PASSWORD_LENGTH or value.startswith("change-me"):
            raise ValueError(
                f"MX_PASSWORD must be at least {MIN_PASSWORD_LENGTH} characters and not the "
                "change-me placeholder. It's the password for the web login page."
            )
        return value


settings = Settings()
