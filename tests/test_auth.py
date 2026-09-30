"""Web login with a session cookie (design.md §10), security headers, static web app."""
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import auth
from api.auth import MAX_FAILURES, SESSION_COOKIE, SESSION_SECONDS, make_session, session_is_valid
from api.config import settings
from api.main import SECURITY_HEADERS, app, mount_web_app
from tests.conftest import TEST_API_KEY, TEST_PASSWORD


@pytest.fixture(autouse=True)
def reset_limiter() -> Iterator[None]:
    auth.limiter.reset()
    yield
    auth.limiter.reset()


@pytest.fixture
def client() -> Iterator[TestClient]:
    # https so the client stores and sends the Secure cookie, like a real browser;
    # `with` runs startup, which creates the (temporary) test database.
    with TestClient(app, base_url="https://testserver") as c:
        yield c


def login(client: TestClient, password: str = TEST_PASSWORD):
    return client.post("/auth/login", json={"password": password})


# --- Login ------------------------------------------------------------------------


def test_login_sets_a_locked_down_session_cookie(client: TestClient):
    r = login(client)
    assert r.status_code == 204
    cookie = r.headers["set-cookie"]
    assert cookie.startswith(f"{SESSION_COOKIE}=")
    for flag in ("HttpOnly", "Secure", "SameSite=strict", "Path=/", f"Max-Age={SESSION_SECONDS}"):
        assert flag.lower() in cookie.lower(), flag


def test_session_cookie_grants_access(client: TestClient):
    assert client.get("/whoami").status_code == 401
    login(client)
    assert client.get("/whoami").status_code == 200
    assert client.get("/conversations").status_code == 200


def test_wrong_password_is_401_and_sets_no_cookie(client: TestClient):
    r = login(client, "wrong password!")
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "wrong_password"
    assert "set-cookie" not in r.headers
    assert client.get("/whoami").status_code == 401


def test_too_many_wrong_passwords_locks_login(client: TestClient):
    for _ in range(MAX_FAILURES):
        assert login(client, "guess-guess-guess").status_code == 401
    r = login(client)  # even the right password is refused while locked
    assert r.status_code == 429
    assert r.json()["detail"]["code"] == "too_many_attempts"
    assert int(r.headers["retry-after"]) > 0
    assert client.get("/whoami", headers={"X-mX-Key": TEST_API_KEY}).status_code == 200  # key still works


def test_success_resets_the_failure_count(client: TestClient):
    for _ in range(MAX_FAILURES - 1):
        login(client, "guess-guess-guess")
    assert login(client).status_code == 204
    for _ in range(MAX_FAILURES - 1):
        assert login(client, "guess-guess-guess").status_code == 401  # not locked yet


def test_logout_clears_the_cookie(client: TestClient):
    login(client)
    r = client.post("/auth/logout")
    assert r.status_code == 204
    assert f'{SESSION_COOKIE}=""' in r.headers["set-cookie"] or "Max-Age=0" in r.headers["set-cookie"]
    assert client.get("/whoami").status_code == 401


def test_api_key_header_still_works(client: TestClient):
    assert client.get("/whoami", headers={"X-mX-Key": TEST_API_KEY}).status_code == 200
    assert client.get("/whoami", headers={"X-mX-Key": "wrong"}).status_code == 401


def test_login_password_length_is_capped(client: TestClient):
    assert login(client, "x" * 1001).status_code == 422


# --- Session tokens -----------------------------------------------------------------


def test_tampered_or_malformed_sessions_are_rejected():
    token = make_session(now=1_000)
    expires, signature = token.split(".")
    assert session_is_valid(token, now=1_000)
    assert not session_is_valid(f"{int(expires) + 1}.{signature}", now=1_000)  # extended expiry
    assert not session_is_valid(f"{expires}.{'0' * len(signature)}", now=1_000)
    for bad in ("", "abc", "123", "abc.def", f"{expires}."):
        assert not session_is_valid(bad, now=1_000)


def test_sessions_expire():
    token = make_session(now=1_000)
    assert session_is_valid(token, now=1_000 + SESSION_SECONDS - 1)
    assert not session_is_valid(token, now=1_000 + SESSION_SECONDS + 1)


def test_changing_the_api_key_signs_everyone_out(monkeypatch: pytest.MonkeyPatch):
    token = make_session(now=1_000)
    monkeypatch.setattr(settings, "mx_api_key", "a-completely-different-key-" + "y" * 20)
    assert not session_is_valid(token, now=1_000)


def test_tampered_cookie_is_401(client: TestClient):
    client.cookies.set(SESSION_COOKIE, "9999999999.forged", domain="testserver")
    assert client.get("/whoami").status_code == 401


def test_old_failures_fall_out_of_the_window():
    limiter = auth.LoginLimiter()
    for i in range(MAX_FAILURES - 1):
        limiter.record_failure(now=float(i))
    limiter.record_failure(now=auth.FAILURE_WINDOW_SECONDS + 100.0)  # earlier ones expired
    assert limiter.seconds_locked(now=auth.FAILURE_WINDOW_SECONDS + 101.0) == 0


# --- Security headers and the web app --------------------------------------------------


def test_security_headers_on_every_response(client: TestClient):
    for path in ("/health", "/whoami"):
        r = client.get(path)
        for name, value in SECURITY_HEADERS.items():
            assert r.headers[name] == value, (path, name)


def test_web_app_is_served_without_shadowing_the_api(tmp_path: Path):
    (tmp_path / "index.html").write_text("<!doctype html><title>mX</title>", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log('mx')", encoding="utf-8")
    demo = FastAPI()

    @demo.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    assert mount_web_app(demo, tmp_path) is True
    web = TestClient(demo)
    assert "<title>mX</title>" in web.get("/").text
    assert web.get("/assets/app.js").text == "console.log('mx')"
    assert web.get("/health").json() == {"status": "ok"}


def test_no_web_app_without_a_build(tmp_path: Path):
    assert mount_web_app(FastAPI(), tmp_path) is False


def test_api_docs_page_is_exempt_from_the_csp(client: TestClient):
    """/docs loads Swagger UI from a CDN; the CSP would blank the page."""
    r = client.get("/docs")
    assert r.status_code == 200
    assert "content-security-policy" not in r.headers
    assert r.headers["x-frame-options"] == "DENY"  # other headers still apply
