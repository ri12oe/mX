"""Image input: decoding/validation, storage, GET /images/{id}, and /chat with images."""
import json
import sqlite3
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api import db
from api.chat import IMAGE_OMITTED
from api.images import MAX_IMAGE_BYTES, MAX_IMAGES, ImageError, decode_image, decode_images, sniff_media_type
from api.main import app, get_db, get_provider
from providers.errors import ProviderUnavailableError
from tests import sample_images as img
from tests.conftest import TEST_API_KEY
from tests.fakes import FakeProvider

HEADERS = {"X-mX-Key": TEST_API_KEY}


@pytest.fixture
def fake() -> FakeProvider:
    return FakeProvider(chunks=["A red square."], model="claude-opus-5-5")


@pytest.fixture
def client(conn: sqlite3.Connection, fake: FakeProvider) -> Iterator[TestClient]:
    app.dependency_overrides[get_db] = lambda: conn
    app.dependency_overrides[get_provider] = lambda: fake
    yield TestClient(app)
    app.dependency_overrides.clear()


def chat(client: TestClient, images: list[str], **body: Any):
    return client.post("/chat", json={"message": "What is this?", "images": images, **body}, headers=HEADERS)


def meta_of(response: Any) -> dict[str, Any]:
    first_data_line = next(line for line in response.text.splitlines() if line.startswith("data: "))
    return json.loads(first_data_line[6:])


def count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# --- Type detection and decoding -------------------------------------------


@pytest.mark.parametrize(
    ("data", "media_type"),
    [(img.png(), "image/png"), (img.JPEG, "image/jpeg"), (img.GIF, "image/gif"), (img.WEBP, "image/webp")],
    ids=["png", "jpeg", "gif", "webp"],
)
def test_sniff_detects_supported_formats(data: bytes, media_type: str):
    assert sniff_media_type(data) == media_type


@pytest.mark.parametrize(
    "data", [img.PDF, b"hello world", b"RIFF\x00\x00\x00\x00WAVEfmt "], ids=["pdf", "text", "wav"]
)
def test_sniff_rejects_other_formats(data: bytes):
    assert sniff_media_type(data) is None


def test_decode_plain_base64_and_data_url():
    data = img.png()
    assert decode_image(img.b64(data)).data == data
    decoded = decode_image("data:image/png;base64," + img.b64(data))
    assert (decoded.media_type, decoded.data) == ("image/png", data)


def test_type_comes_from_bytes_not_the_data_url():
    """A client can't label a PDF as an image."""
    with pytest.raises(ImageError, match="JPEG, PNG, GIF, or WebP"):
        decode_image("data:image/png;base64," + img.b64(img.PDF))


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("not base64!!", "not valid base64"),
        ("", "empty"),
        (img.b64(img.PDF), "JPEG, PNG, GIF, or WebP"),
    ],
    ids=["bad-base64", "empty", "pdf"],
)
def test_decode_rejects_bad_images(value: str, message: str):
    with pytest.raises(ImageError, match=message):
        decode_image(value)


def test_decode_rejects_images_over_5_mb():
    too_big = img.b64(img.JPEG + b"\x00" * MAX_IMAGE_BYTES)  # built at run time, not in the test name
    with pytest.raises(ImageError, match="larger than 5 MB"):
        decode_image(too_big)


def test_decode_images_limits_count_and_names_the_bad_one():
    with pytest.raises(ImageError, match=f"At most {MAX_IMAGES}"):
        decode_images([img.b64(img.png())] * (MAX_IMAGES + 1))
    with pytest.raises(ImageError, match="Image 2"):
        decode_images([img.b64(img.png()), "bad!!"])


# --- Storage ---------------------------------------------------------------


def test_save_turn_stores_images_and_refs(conn: sqlite3.Connection):
    image = db.NewImage(db.new_id(), "image/png", img.png())
    turn = db.Turn(
        conversation_id="c1", user_message_id=db.new_id(), user_content="look",
        user_created_at=db.now_iso(), assistant_message_id=db.new_id(), assistant_content="ok",
        usage=db.UsageRecord("fake", "m", "v", 1, 1, None, 1), user_images=(image,),
    )
    db.save_turn(conn, turn)

    user_message = db.get_conversation(conn, "c1")["messages"][0]  # type: ignore[index]
    assert user_message["image_refs"] == [image.id]
    assert db.get_image(conn, image.id) == ("image/png", image.data)
    assert db.get_image(conn, "nope") is None


# --- /chat with images -----------------------------------------------------


def test_chat_sends_images_to_the_provider_on_the_current_message(client: TestClient, fake: FakeProvider):
    data = img.png()
    assert chat(client, [img.b64(data), img.b64(img.JPEG)]).status_code == 200

    sent = fake.calls[0].messages[-1]
    assert sent.content == "What is this?"
    assert [(i.media_type, i.data) for i in sent.images or []] == [("image/png", data), ("image/jpeg", img.JPEG)]


def test_chat_saves_images_and_serves_them(client: TestClient):
    data = img.png()
    conversation_id = meta_of(chat(client, [img.b64(data)]))["conversation_id"]

    user_message = client.get(f"/conversations/{conversation_id}", headers=HEADERS).json()["messages"][0]
    assert len(user_message["image_refs"]) == 1

    r = client.get(f"/images/{user_message['image_refs'][0]}", headers=HEADERS)
    assert r.status_code == 200
    assert r.content == data
    assert r.headers["content-type"] == "image/png"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_follow_up_replaces_old_images_with_a_marker(client: TestClient, fake: FakeProvider):
    conversation_id = meta_of(chat(client, [img.b64(img.png()), img.b64(img.GIF)]))["conversation_id"]
    chat(client, [], conversation_id=conversation_id, message="And now?")

    history = fake.calls[1].messages
    assert history[0].images is None
    assert history[0].content == f"{IMAGE_OMITTED}\n{IMAGE_OMITTED}\nWhat is this?"
    assert (history[-1].content, history[-1].images) == ("And now?", None)


@pytest.mark.parametrize(
    "images",
    [["not base64!!"], [img.b64(img.PDF)], [img.b64(img.png())] * (MAX_IMAGES + 1)],
    ids=["bad-base64", "pdf", "too-many"],
)
def test_chat_rejects_bad_images_before_calling_the_model(
    client: TestClient, fake: FakeProvider, conn: sqlite3.Connection, images: list[str],
):
    r = chat(client, images)
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "invalid_image"
    assert fake.calls == []
    assert count(conn, "images") == 0


def test_failed_turn_saves_no_images(client: TestClient, fake: FakeProvider, conn: sqlite3.Connection):
    fake.chunks, fake.error, fake.fail_after = ["a", "b"], ProviderUnavailableError("lost"), 1
    chat(client, [img.b64(img.png())])
    assert count(conn, "images") == 0


def test_deleting_the_conversation_deletes_its_images(client: TestClient, conn: sqlite3.Connection):
    conversation_id = meta_of(chat(client, [img.b64(img.png())]))["conversation_id"]
    assert count(conn, "images") == 1
    client.delete(f"/conversations/{conversation_id}", headers=HEADERS)
    assert count(conn, "images") == 0


# --- GET /images/{id} --------------------------------------------------------


def test_get_image_requires_key(client: TestClient):
    assert client.get("/images/anything").status_code == 401


def test_get_unknown_image_is_404(client: TestClient):
    assert client.get("/images/nope", headers=HEADERS).status_code == 404
