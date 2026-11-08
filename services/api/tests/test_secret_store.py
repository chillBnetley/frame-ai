from __future__ import annotations

import base64
import os
import stat
import sys
from pathlib import Path
from typing import Any

import pytest

from app.services import secret_store
from app.services.secret_store import (
    ALGORITHM,
    MASTER_KEY_BYTES,
    MASTER_KEY_FILENAME,
    NONCE_BYTES,
    TAG_BYTES,
    DpapiMasterKeyStore,
    FileMasterKeyStore,
    InMemoryMasterKeyStore,
    KeychainMasterKeyStore,
    SecretBlob,
    SecretBox,
    SecretStoreError,
    blob_from_record,
    blob_to_record,
    default_master_key_store,
    provider_settings_aad,
    write_private_document,
)

posix_only = pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX file modes are not enforced on Windows",
)

_PLAINTEXT = "sk-unit-test-secret-value"
_AAD = provider_settings_aad("vision")


def _box(key: bytes | None = None) -> SecretBox:
    return SecretBox(InMemoryMasterKeyStore(key))


def test_aad_binds_the_document_version_and_kind():
    assert _AAD == b"frame-ai/provider-settings/v2/vision"
    assert provider_settings_aad("decision") == b"frame-ai/provider-settings/v2/decision"


def test_roundtrip_returns_the_plaintext_and_a_tagged_ciphertext():
    box = _box()

    blob = box.encrypt(_PLAINTEXT, _AAD)

    assert blob.alg == ALGORITHM
    assert len(blob.nonce) == NONCE_BYTES
    assert len(blob.ciphertext) == len(_PLAINTEXT.encode("utf-8")) + TAG_BYTES
    assert box.decrypt(blob, _AAD) == _PLAINTEXT


def test_each_encryption_uses_a_fresh_nonce_and_ciphertext():
    box = _box()

    first = box.encrypt(_PLAINTEXT, _AAD)
    second = box.encrypt(_PLAINTEXT, _AAD)

    assert first.nonce != second.nonce
    assert first.ciphertext != second.ciphertext
    assert box.decrypt(first, _AAD) == box.decrypt(second, _AAD) == _PLAINTEXT


@pytest.mark.parametrize("position", [0, len(_PLAINTEXT) // 2, -1])
def test_flipping_any_ciphertext_byte_fails_closed(position: int):
    box = _box()
    blob = box.encrypt(_PLAINTEXT, _AAD)
    raw = bytearray(blob.ciphertext)
    raw[position] ^= 0x01
    tampered = SecretBlob(nonce=blob.nonce, ciphertext=bytes(raw))

    with pytest.raises(SecretStoreError) as error:
        box.decrypt(tampered, _AAD)

    assert _PLAINTEXT not in str(error.value)
    assert blob.ciphertext.hex() not in str(error.value)


def test_swapping_the_aad_between_providers_fails():
    box = _box()
    blob = box.encrypt(_PLAINTEXT, _AAD)

    with pytest.raises(SecretStoreError):
        box.decrypt(blob, provider_settings_aad("decision"))


def test_a_different_master_key_cannot_decrypt():
    blob = _box().encrypt(_PLAINTEXT, _AAD)

    with pytest.raises(SecretStoreError):
        _box().decrypt(blob, _AAD)


def test_tampered_nonce_fails():
    box = _box()
    blob = box.encrypt(_PLAINTEXT, _AAD)
    raw = bytearray(blob.nonce)
    raw[0] ^= 0x01

    with pytest.raises(SecretStoreError):
        box.decrypt(SecretBlob(nonce=bytes(raw), ciphertext=blob.ciphertext), _AAD)


@pytest.mark.parametrize("length", [0, 16, 24, 31, 33, 64])
def test_master_key_length_is_enforced(length: int):
    box = _box(bytes(length))

    with pytest.raises(SecretStoreError) as error:
        box.encrypt(_PLAINTEXT, _AAD)

    assert "master key" in str(error.value)
    with pytest.raises(SecretStoreError):
        box.decrypt(SecretBlob(nonce=bytes(NONCE_BYTES), ciphertext=bytes(TAG_BYTES)), _AAD)


@pytest.mark.parametrize("length", [0, 8, 11, 13, 16, 128])
def test_nonce_length_is_enforced(length: int):
    box = _box()

    with pytest.raises(SecretStoreError):
        box.decrypt(SecretBlob(nonce=bytes(length), ciphertext=bytes(TAG_BYTES + 1)), _AAD)


@pytest.mark.parametrize("length", [0, 1, TAG_BYTES - 1])
def test_ciphertext_must_carry_a_tag(length: int):
    box = _box()

    with pytest.raises(SecretStoreError):
        box.decrypt(SecretBlob(nonce=bytes(NONCE_BYTES), ciphertext=bytes(length)), _AAD)


def test_unknown_algorithm_is_rejected():
    box = _box()
    blob = box.encrypt(_PLAINTEXT, _AAD)

    with pytest.raises(SecretStoreError):
        box.decrypt(
            SecretBlob(nonce=blob.nonce, ciphertext=blob.ciphertext, alg="AES-128-GCM"), _AAD
        )


def test_record_roundtrip_and_malformed_base64():
    blob = _box().encrypt(_PLAINTEXT, _AAD)
    record = blob_to_record(blob)

    assert record["alg"] == ALGORITHM
    assert base64.b64decode(record["nonce"]) == blob.nonce
    restored = blob_from_record(record["alg"], record["nonce"], record["ciphertext"])
    assert restored == blob

    for nonce, ciphertext in [
        ("not-base64!", record["ciphertext"]),
        (record["nonce"], "%%%%"),
        ("", record["ciphertext"]),
        (record["nonce"], ""),
        ("é" * 16, record["ciphertext"]),
    ]:
        with pytest.raises(SecretStoreError):
            blob_from_record(ALGORITHM, nonce, ciphertext)


def test_record_rejects_wrong_decoded_lengths():
    with pytest.raises(SecretStoreError):
        blob_from_record(ALGORITHM, base64.b64encode(bytes(8)).decode(), "AAAAAAAAAAAAAAAAAAAAAA==")
    with pytest.raises(SecretStoreError):
        blob_from_record(ALGORITHM, base64.b64encode(bytes(12)).decode(), "AAAA")


def test_in_memory_store_hands_out_copies():
    store = InMemoryMasterKeyStore()
    first = store.load_or_create()
    first[0] ^= 0xFF

    assert store.load_or_create() != first
    assert len(store.load_or_create()) == MASTER_KEY_BYTES


@posix_only
def test_file_store_creates_a_private_key_and_reuses_it(tmp_path: Path):
    path = tmp_path / MASTER_KEY_FILENAME
    store = FileMasterKeyStore(path)

    key = store.load_or_create()

    assert len(key) == MASTER_KEY_BYTES
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert path.read_bytes() == bytes(key)
    assert FileMasterKeyStore(path).load_or_create() == key


@posix_only
def test_file_store_repairs_loose_permissions_before_use(tmp_path: Path):
    path = tmp_path / MASTER_KEY_FILENAME
    key = FileMasterKeyStore(path).load_or_create()
    path.chmod(0o644)

    assert FileMasterKeyStore(path).load_or_create() == key
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@posix_only
def test_file_store_fails_closed_when_permissions_cannot_be_repaired(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    path = tmp_path / MASTER_KEY_FILENAME
    FileMasterKeyStore(path).load_or_create()
    path.chmod(0o644)
    monkeypatch.setattr(os, "chmod", lambda *args, **kwargs: None)

    with pytest.raises(SecretStoreError) as error:
        FileMasterKeyStore(path).load_or_create()

    assert "private" in str(error.value)


@posix_only
def test_file_store_rejects_a_damaged_key(tmp_path: Path):
    path = tmp_path / MASTER_KEY_FILENAME
    path.write_bytes(b"too-short")
    path.chmod(0o600)

    with pytest.raises(SecretStoreError) as error:
        FileMasterKeyStore(path).load_or_create()

    assert "Re-enter the API keys" in str(error.value)


def _fake_dpapi() -> tuple[Any, Any]:
    def protect(raw: bytes) -> bytes:
        return b"sealed:" + raw

    def unprotect(raw: bytes) -> bytes:
        if not raw.startswith(b"sealed:"):
            raise SecretStoreError("The provider master key is unavailable or damaged.")
        return raw[len(b"sealed:") :]

    return protect, unprotect


def test_dpapi_store_persists_only_the_sealed_blob(tmp_path: Path):
    protect, unprotect = _fake_dpapi()
    path = tmp_path / MASTER_KEY_FILENAME
    store = DpapiMasterKeyStore(path, protect=protect, unprotect=unprotect)

    key = store.load_or_create()

    assert len(key) == MASTER_KEY_BYTES
    assert path.read_bytes() == b"sealed:" + bytes(key)
    assert path.read_bytes() != bytes(key)
    assert DpapiMasterKeyStore(path, protect=protect, unprotect=unprotect).load_or_create() == key


def test_dpapi_store_does_not_depend_on_chmod(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    protect, unprotect = _fake_dpapi()

    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("DPAPI protection must not rely on chmod")

    monkeypatch.setattr(os, "chmod", forbidden)
    path = tmp_path / MASTER_KEY_FILENAME

    key = DpapiMasterKeyStore(path, protect=protect, unprotect=unprotect).load_or_create()

    assert len(key) == MASTER_KEY_BYTES
    assert path.exists()


def test_dpapi_store_fails_closed_on_a_tampered_blob(tmp_path: Path):
    protect, unprotect = _fake_dpapi()
    path = tmp_path / MASTER_KEY_FILENAME
    DpapiMasterKeyStore(path, protect=protect, unprotect=unprotect).load_or_create()
    path.write_bytes(b"tampered")

    with pytest.raises(SecretStoreError):
        DpapiMasterKeyStore(path, protect=protect, unprotect=unprotect).load_or_create()


def test_dpapi_store_fails_closed_when_protection_fails(tmp_path: Path):
    def broken(raw: bytes) -> bytes:
        raise OSError("DPAPI unavailable")

    path = tmp_path / MASTER_KEY_FILENAME

    with pytest.raises(SecretStoreError):
        DpapiMasterKeyStore(path, protect=broken, unprotect=lambda raw: raw).load_or_create()

    assert not path.exists()


def test_dpapi_store_rejects_a_wrong_length_plaintext(tmp_path: Path):
    path = tmp_path / MASTER_KEY_FILENAME
    path.write_bytes(b"sealed:short")

    with pytest.raises(SecretStoreError):
        DpapiMasterKeyStore(
            path,
            protect=lambda raw: raw,
            unprotect=lambda raw: raw[len(b"sealed:") :],
        ).load_or_create()


class _FakeBridge:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], bytes] = {}
        self.added: list[tuple[str, str, bytes]] = []

    def find(self, service: str, account: str) -> bytes | None:
        return self.items.get((service, account))

    def add(self, service: str, account: str, secret: bytes) -> None:
        self.added.append((service, account, secret))
        self.items[(service, account)] = secret


def test_keychain_store_creates_and_reuses_an_item():
    bridge = _FakeBridge()
    store = KeychainMasterKeyStore("frame-ai", "account", bridge=bridge)

    key = store.load_or_create()

    assert len(key) == MASTER_KEY_BYTES
    assert len(bridge.added) == 1
    service, account, secret = bridge.added[0]
    assert (service, account) == ("frame-ai", "account")
    assert base64.b64decode(secret) == bytes(key)
    assert KeychainMasterKeyStore("frame-ai", "account", bridge=bridge).load_or_create() == key


def test_keychain_store_rejects_damaged_items():
    bridge = _FakeBridge()
    bridge.items[("frame-ai", "account")] = b"not-base64!"

    with pytest.raises(SecretStoreError):
        KeychainMasterKeyStore("frame-ai", "account", bridge=bridge).load_or_create()

    bridge.items[("frame-ai", "account")] = base64.b64encode(b"short")
    with pytest.raises(SecretStoreError):
        KeychainMasterKeyStore("frame-ai", "account", bridge=bridge).load_or_create()


def test_keychain_store_propagates_bridge_failures():
    class Broken:
        def find(self, service: str, account: str) -> bytes | None:
            raise SecretStoreError("The provider master key is unavailable or damaged.")

        def add(self, service: str, account: str, secret: bytes) -> None:
            raise AssertionError("must not create a key after a lookup failure")

    with pytest.raises(SecretStoreError):
        KeychainMasterKeyStore("frame-ai", "account", bridge=Broken()).load_or_create()


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        ("win32", DpapiMasterKeyStore),
        ("darwin", KeychainMasterKeyStore),
        ("linux", FileMasterKeyStore),
    ],
)
def test_default_store_follows_the_platform(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    expected: type,
):
    monkeypatch.setattr(secret_store.sys, "platform", platform)

    store = default_master_key_store(tmp_path)

    assert isinstance(store, expected)


def test_write_private_document_replaces_atomically(tmp_path: Path):
    path = tmp_path / "nested" / "provider-settings.json"
    write_private_document(path, b"first")
    write_private_document(path, b"second")

    assert path.read_bytes() == b"second"
    assert not path.with_name(path.name + ".tmp").exists()


def test_write_private_document_keeps_the_original_when_replace_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    path = tmp_path / "provider-settings.json"
    write_private_document(path, b"original")

    def broken(src: Any, dst: Any) -> None:
        raise OSError("replace denied")

    monkeypatch.setattr(os, "replace", broken)

    with pytest.raises(OSError):
        write_private_document(path, b"replacement")

    assert path.read_bytes() == b"original"
    assert not path.with_name(path.name + ".tmp").exists()


def test_write_private_document_cleans_up_when_fsync_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    path = tmp_path / "provider-settings.json"
    write_private_document(path, b"original")

    def broken(descriptor: int) -> None:
        raise OSError("fsync denied")

    monkeypatch.setattr(os, "fsync", broken)

    with pytest.raises(OSError):
        write_private_document(path, b"replacement")

    assert path.read_bytes() == b"original"
    assert not path.with_name(path.name + ".tmp").exists()


@posix_only
def test_write_private_document_creates_a_private_file(tmp_path: Path):
    path = tmp_path / "provider-settings.json"

    write_private_document(path, b"payload")

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


# --- D1: a missing master key must never be silently replaced -----------------


def test_file_store_refuses_to_mint_a_replacement_key(tmp_path: Path):
    path = tmp_path / MASTER_KEY_FILENAME

    with pytest.raises(SecretStoreError) as error:
        FileMasterKeyStore(path, create_if_missing=False).load_or_create()

    assert "Re-enter the API keys" in str(error.value)
    assert str(error.value) == secret_store._MASTER_KEY_MESSAGE
    assert not path.exists()
    assert list(tmp_path.iterdir()) == []


def test_file_store_still_creates_the_first_key(tmp_path: Path):
    path = tmp_path / MASTER_KEY_FILENAME

    key = FileMasterKeyStore(path, create_if_missing=True).load_or_create()

    assert len(key) == MASTER_KEY_BYTES
    assert path.exists()


def test_dpapi_store_refuses_to_mint_a_replacement_key(tmp_path: Path):
    protect, unprotect = _fake_dpapi()
    path = tmp_path / MASTER_KEY_FILENAME

    with pytest.raises(SecretStoreError) as error:
        DpapiMasterKeyStore(
            path,
            protect=protect,
            unprotect=unprotect,
            create_if_missing=False,
        ).load_or_create()

    assert str(error.value) == secret_store._MASTER_KEY_MESSAGE
    assert not path.exists()
    assert list(tmp_path.iterdir()) == []


def test_dpapi_store_never_calls_protect_when_creation_is_forbidden(tmp_path: Path):
    def forbidden(raw: bytes) -> bytes:
        raise AssertionError("a replacement key must not even be sealed")

    path = tmp_path / MASTER_KEY_FILENAME

    with pytest.raises(SecretStoreError):
        DpapiMasterKeyStore(
            path,
            protect=forbidden,
            unprotect=lambda raw: raw,
            create_if_missing=False,
        ).load_or_create()

    assert not path.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="real DPAPI is Windows only")
def test_real_dpapi_store_refuses_to_replace_a_deleted_key(tmp_path: Path):
    path = tmp_path / MASTER_KEY_FILENAME
    original = DpapiMasterKeyStore(path).load_or_create()
    sealed = path.read_bytes()
    assert sealed.startswith(b"\x01\x00\x00\x00")
    assert DpapiMasterKeyStore(path).load_or_create() == original
    path.unlink()

    with pytest.raises(SecretStoreError) as error:
        DpapiMasterKeyStore(path, create_if_missing=False).load_or_create()

    assert str(error.value) == secret_store._MASTER_KEY_MESSAGE
    assert not path.exists()
    assert list(tmp_path.iterdir()) == []


def test_keychain_store_refuses_to_mint_a_replacement_item():
    bridge = _FakeBridge()

    with pytest.raises(SecretStoreError) as error:
        KeychainMasterKeyStore(
            "frame-ai",
            "account",
            bridge=bridge,
            create_if_missing=False,
        ).load_or_create()

    assert str(error.value) == secret_store._MASTER_KEY_MESSAGE
    assert bridge.added == []
    assert bridge.items == {}


def test_keychain_store_reads_an_existing_item_when_creation_is_forbidden():
    bridge = _FakeBridge()
    key = KeychainMasterKeyStore("frame-ai", "account", bridge=bridge).load_or_create()

    reused = KeychainMasterKeyStore(
        "frame-ai",
        "account",
        bridge=bridge,
        create_if_missing=False,
    ).load_or_create()

    assert reused == key
    assert len(bridge.added) == 1


@posix_only
def test_file_store_reads_an_existing_key_when_creation_is_forbidden(tmp_path: Path):
    path = tmp_path / MASTER_KEY_FILENAME
    raw = bytes(range(MASTER_KEY_BYTES))
    path.write_bytes(raw)
    path.chmod(0o600)

    assert FileMasterKeyStore(path, create_if_missing=False).load_or_create() == bytearray(raw)


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        ("win32", DpapiMasterKeyStore),
        ("darwin", KeychainMasterKeyStore),
        ("linux", FileMasterKeyStore),
    ],
)
def test_default_store_forwards_the_creation_decision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    expected: type,
):
    monkeypatch.setattr(secret_store.sys, "platform", platform)

    strict = default_master_key_store(tmp_path, allow_create=False)
    permissive = default_master_key_store(tmp_path)

    assert isinstance(strict, expected)
    assert isinstance(permissive, expected)
    assert strict._create_if_missing is False
    assert permissive._create_if_missing is True


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux", "freebsd"])
def test_default_store_refuses_creation_on_every_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
):
    monkeypatch.setattr(secret_store.sys, "platform", platform)
    if platform == "darwin":
        # The real bridge would reach Security.framework; inject the fake seam.
        monkeypatch.setattr(
            secret_store,
            "SecurityFrameworkBridge",
            _FakeBridge,
        )
    store = default_master_key_store(tmp_path, allow_create=False)

    with pytest.raises(SecretStoreError) as error:
        store.load_or_create()

    assert str(error.value) == secret_store._MASTER_KEY_MESSAGE
    assert not (tmp_path / MASTER_KEY_FILENAME).exists()
    assert list(tmp_path.iterdir()) == []
