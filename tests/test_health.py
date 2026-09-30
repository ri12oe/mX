from fastapi.testclient import TestClient

from api.config import settings
from api.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_whoami_requires_key():
    assert client.get("/whoami").status_code == 401


def test_whoami_with_key():
    r = client.get("/whoami", headers={"X-Jarvis-Key": settings.jarvis_api_key})
    assert r.status_code == 200
    assert r.json()["assistant"] == "Jarvis"
