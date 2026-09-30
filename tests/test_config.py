import pytest
from pydantic import ValidationError

from api.config import MIN_KEY_LENGTH, Settings


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
    key = "k" * MIN_KEY_LENGTH
    assert make_settings(key).mx_api_key == key


def test_error_does_not_echo_the_key():
    secret = "change-me-but-this-is-secret-9f8e7d6c5b4a"
    with pytest.raises(ValidationError) as exc:
        make_settings(secret)
    assert secret not in str(exc.value)
