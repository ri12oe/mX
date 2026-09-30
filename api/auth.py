"""Web login (design.md §10): password -> signed, HttpOnly session cookie.

The cookie is stateless: "<expiry>.<HMAC-SHA256(MX_API_KEY, expiry)>".
Changing MX_API_KEY signs everyone out. Scripts keep using the X-mX-Key header.
"""
import hashlib
import hmac
import time
from collections import deque

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from api.config import settings

SESSION_COOKIE = "mx_session"
SESSION_SECONDS = 30 * 24 * 60 * 60
MAX_FAILURES = 5
FAILURE_WINDOW_SECONDS = 15 * 60
LOCKOUT_SECONDS = 15 * 60

router = APIRouter(prefix="/auth")


# --- Session tokens ---------------------------------------------------------------


def _signature(expires: int) -> str:
    message = f"mx-session:{expires}".encode()
    return hmac.new(settings.mx_api_key.encode(), message, hashlib.sha256).hexdigest()


def make_session(now: float | None = None) -> str:
    expires = int(now if now is not None else time.time()) + SESSION_SECONDS
    return f"{expires}.{_signature(expires)}"


def session_is_valid(token: str, now: float | None = None) -> bool:
    expires_text, _, signature = token.partition(".")
    if not expires_text.isdigit() or not signature:
        return False
    expires = int(expires_text)
    if expires < (now if now is not None else time.time()):
        return False
    return hmac.compare_digest(signature.encode(), _signature(expires).encode())


# --- Brute-force protection -------------------------------------------------------


class LoginLimiter:
    """After MAX_FAILURES wrong passwords in the window, refuse logins for a while.

    In memory and global (one user, one instance). Trade-off: someone guessing
    can also lock the owner out for LOCKOUT_SECONDS; the API key still works.
    """

    def __init__(self) -> None:
        self.failures: deque[float] = deque()
        self.locked_until = 0.0

    def seconds_locked(self, now: float) -> int:
        return max(0, int(self.locked_until - now) + 1) if now < self.locked_until else 0

    def record_failure(self, now: float) -> None:
        self.failures.append(now)
        while self.failures and self.failures[0] < now - FAILURE_WINDOW_SECONDS:
            self.failures.popleft()
        if len(self.failures) >= MAX_FAILURES:
            self.locked_until = now + LOCKOUT_SECONDS
            self.failures.clear()

    def reset(self) -> None:
        self.failures.clear()
        self.locked_until = 0.0


limiter = LoginLimiter()


# --- Routes -----------------------------------------------------------------------


class LoginRequest(BaseModel):
    password: str = Field(max_length=1000)


def _cookie_options() -> dict[str, object]:
    return {"httponly": True, "secure": settings.cookie_secure, "samesite": "strict", "path": "/"}


@router.post("/login", status_code=204)
def login(body: LoginRequest, response: Response) -> None:
    """Check the password and set the session cookie."""
    now = time.time()
    wait = limiter.seconds_locked(now)
    if wait:
        raise HTTPException(
            status_code=429,
            detail={"code": "too_many_attempts", "message": f"Too many wrong passwords. Try again in {wait // 60 + 1} minutes."},
            headers={"Retry-After": str(wait)},
        )
    if not hmac.compare_digest(body.password.encode(), settings.mx_password.encode()):
        limiter.record_failure(now)
        raise HTTPException(status_code=401, detail={"code": "wrong_password", "message": "Wrong password."})
    limiter.reset()
    response.set_cookie(SESSION_COOKIE, make_session(now), max_age=SESSION_SECONDS, **_cookie_options())


@router.post("/logout", status_code=204)
def logout(response: Response) -> None:
    """Clear the session cookie."""
    response.delete_cookie(SESSION_COOKIE, **_cookie_options())
