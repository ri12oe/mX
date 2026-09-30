from pathlib import Path

import pytest
from pydantic import ValidationError

from api.config import MIN_KEY_LENGTH, Settings

STRONG_KEY = "k" * MIN_KEY_LENGTH


def make_settings(key: str) -> Settings:
    """Build Settings from the given key only, ignoring .env."""
    return Settings(_env_file=None, mx_api_key=key)


@pytest.mark.parametrize(
    "bad_key",
    [
        "",
        "change-me",
        "change-me-to-a-long-random-string",
        "x" * (MIN_KEY_LENGTH - 1),
    ],
)
def test_weak_key_refuses_to_start(bad_key: str):
    with pytest.raises(ValidationError):
        make_settings(bad_key)


def test_strong_key_is_accepted():
    assert make_settings(STRONG_KEY).mx_api_key == STRONG_KEY


def test_defaults_match_design(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DB_PATH", raising=False)  # conftest points it at a temp dir
    s = make_settings(STRONG_KEY)
    assert s.db_path == "./data/mx.db"
    assert s.cors_origins == ["http://localhost:5173"]


def test_default_system_prompt_file_exists():
    assert Path(make_settings(STRONG_KEY).system_prompt_file).is_file()


def test_cors_origins_parsed_from_json_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CORS_ORIGINS", '["http://a.test", "http://b.test"]')
    assert make_settings(STRONG_KEY).cors_origins == ["http://a.test", "http://b.test"]


def test_error_does_not_echo_the_key():
    secret = "change-me-but-this-is-secret-9f8e7d6c5b4a"
    with pytest.raises(ValidationError) as exc:
        make_settings(secret)
    assert secret not in str(exc.value)
