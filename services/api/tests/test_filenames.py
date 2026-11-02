from __future__ import annotations

import json
from unicodedata import normalize as unicode_normalize

import pytest
from fastapi.testclient import TestClient

from app.api.routes.images import _content_disposition
from app.core.config import Settings
from app.services.image_service import sanitize_original_name
from tests.conftest import make_image, upload


@pytest.mark.parametrize(
    ("raw_name", "expected"),
    [
        ("../../etc/passwd.png", "passwd.png"),
        ('a"b.png', "a%22b.png"),
        ("x\r\nSet-Cookie: a=b.png", "x%0D%0ASet-Cookie: a=b.png"),
        ("   ", "image"),
        ("图片🙂.jpg", "图片🙂.jpg"),
        (r"C:\Windows\System32\evil.png", "evil.png"),
    ],
)
def test_malicious_filenames_are_sanitized(
    client: TestClient,
    settings: Settings,
    raw_name: str,
    expected: str,
):
    response = upload(client, make_image("PNG"), raw_name, "image/png")

    assert response.status_code == 201
    body = response.json()
    assert body["originalName"] == expected

    original = client.get(f"/api/v1/images/{body['imageId']}/original")
    disposition = original.headers["content-disposition"]
    assert "\r" not in disposition
    assert "\n" not in disposition
    assert "filename*=UTF-8''" in disposition
    assert original.headers["x-content-type-options"] == "nosniff"
    assert original.headers["content-security-policy"] == "default-src 'none'; sandbox"
    assert "immutable" in original.headers["cache-control"]
    assert "set-cookie" not in original.headers

    registry = json.loads(settings.registry_path.read_text(encoding="utf-8"))
    assert registry["images"][body["imageId"]]["original_name"] == expected
    assert (settings.data_dir / "originals" / f"{body['imageId']}.png").is_file()
    assert not (settings.data_dir.parent / "passwd.png").exists()


def test_long_filename_is_truncated_to_255_utf8_bytes(client: TestClient):
    raw_name = "长" * 300 + ".png"

    response = upload(client, make_image("PNG"), raw_name, "image/png")

    assert response.status_code == 201
    original_name = response.json()["originalName"]
    assert len(original_name.encode("utf-8")) <= 255
    assert original_name


def test_original_name_is_unicode_nfc():
    decomposed = "e\u0301.png"

    assert sanitize_original_name(decomposed) == unicode_normalize("NFC", decomposed)
    assert sanitize_original_name("..\\..\\evil.png") == "evil.png"
    assert sanitize_original_name(None) == "image"
    assert sanitize_original_name(".") == "image"
    assert sanitize_original_name("..") == "image"


def test_control_characters_never_reach_original_name():
    assert sanitize_original_name("x\r\nSet-Cookie: a=b.png") == "xSet-Cookie: a=b.png"
    assert sanitize_original_name("a\x00b.png") == "ab.png"
    assert sanitize_original_name("\x1b[31mred.png") == "[31mred.png"
    assert sanitize_original_name('a"b.png') == 'a"b.png'


def test_ascii_disposition_fallback_cannot_break_the_header():
    header = _content_disposition("inline", 'a"b\\c\r\nd.png')

    assert "\r" not in header
    assert "\n" not in header
    assert 'filename="abcd.png"' in header
    assert "filename*=UTF-8''a%22b%5Cc%0D%0Ad.png" in header
