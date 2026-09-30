from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def preflight(origin: str):
    """Simulate the OPTIONS request a browser sends before a cross-origin call."""
    return client.options(
        "/whoami",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "x-mx-key",
        },
    )


def test_cors_allows_vite_dev_server():
    r = preflight("http://localhost:5173")
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "x-mx-key" in r.headers["access-control-allow-headers"].lower()


def test_cors_blocks_unknown_origin():
    r = preflight("http://evil.example")
    assert r.status_code == 400
    assert "access-control-allow-origin" not in r.headers
