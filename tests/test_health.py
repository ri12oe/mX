from fastapi.testclient import TestClient

from tests.conftest import TEST_API_KEY
from api.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_whoami_requires_key():
    assert client.get("/whoami").status_code == 401


def test_whoami_rejects_wrong_key():
    wrong = TEST_API_KEY[:-1] + "y"  # same length, last char differs
    assert client.get("/whoami", headers={"X-mX-Key": wrong}).status_code == 401


def test_whoami_rejects_key_of_different_length():
    assert client.get("/whoami", headers={"X-mX-Key": "short"}).status_code == 401


def test_whoami_with_key():
    r = client.get("/whoami", headers={"X-mX-Key": TEST_API_KEY})
    assert r.status_code == 200
    assert r.json()["assistant"] == "mX"
