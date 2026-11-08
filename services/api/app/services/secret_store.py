"""Encrypted storage for provider API keys.

The settings document never holds plaintext keys: each key is sealed with
AES-256-GCM under a 32-byte master key that lives outside the document. The
master key backend is platform specific (Windows DPAPI, macOS Keychain, POSIX
0600 file) and every failure is fail-closed -- nothing here falls back to
plaintext.

All error messages are static. They never contain key material, ciphertext,
nonces, file paths or stack details.
"""

from __future__ import annotations

import base64
import binascii
import ctypes
import os
import stat
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MASTER_KEY_FILENAME = "provider-master-key"
MASTER_KEY_BYTES = 32
NONCE_BYTES = 12
TAG_BYTES = 16
ALGORITHM = "AES-256-GCM"
_AAD_PREFIX = b"frame-ai/provider-settings/v2/"

_MASTER_KEY_MESSAGE = (
    "The provider master key is unavailable or damaged. Re-enter the API keys in model settings."
)
_DECRYPT_MESSAGE = (
    "The saved provider API key could not be decrypted. Re-enter the API key in model settings."
)
_ENCRYPT_MESSAGE = "The provider API key could not be encrypted."
_PERMISSION_MESSAGE = "The provider master key file is not private enough to use."


class SecretStoreError(RuntimeError):
    """A fail-closed secret storage failure with a safe, static message."""


@dataclass(frozen=True, slots=True)
class SecretBlob:
    """A sealed key: 12-byte nonce and ciphertext carrying the 16-byte GCM tag."""

    nonce: bytes
    ciphertext: bytes
    alg: str = ALGORITHM


class MasterKeyStore(Protocol):
    """Returns a caller-owned 32-byte master key, creating it on first use.

    Whether creation is allowed is a backend construction concern, not part of
    this call: backends built with ``create_if_missing=False`` raise
    ``SecretStoreError`` when the key is absent instead of minting one.
    """

    def load_or_create(self) -> bytearray: ...


def provider_settings_aad(kind: str) -> bytes:
    """Bind a ciphertext to the document format version and the provider role."""

    return _AAD_PREFIX + kind.encode("ascii")


class SecretBox:
    """AES-256-GCM sealing with explicit key/nonce length enforcement.

    ``AESGCM`` itself accepts 16/24/32-byte keys and 8-128 byte nonces, so the
    length checks here are what actually guarantee AES-256 with a 96-bit nonce.
    """

    def __init__(self, key_store: MasterKeyStore) -> None:
        self._key_store = key_store
        self._key: bytes | None = None

    def encrypt(self, plaintext: str, aad: bytes) -> SecretBlob:
        key = self._master_key()
        nonce = os.urandom(NONCE_BYTES)
        try:
            ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), aad)
        except (ValueError, OverflowError, UnicodeError):
            raise SecretStoreError(_ENCRYPT_MESSAGE) from None
        return SecretBlob(nonce=nonce, ciphertext=ciphertext)

    def decrypt(self, blob: SecretBlob, aad: bytes) -> str:
        key = self._master_key()
        if blob.alg != ALGORITHM:
            raise SecretStoreError(_DECRYPT_MESSAGE)
        if len(blob.nonce) != NONCE_BYTES or len(blob.ciphertext) < TAG_BYTES:
            raise SecretStoreError(_DECRYPT_MESSAGE)
        try:
            plaintext = AESGCM(key).decrypt(blob.nonce, blob.ciphertext, aad)
            return plaintext.decode("utf-8")
        except (InvalidTag, ValueError, UnicodeError):
            raise SecretStoreError(_DECRYPT_MESSAGE) from None

    def _master_key(self) -> bytes:
        if self._key is not None:
            return self._key
        material = self._key_store.load_or_create()
        if len(material) != MASTER_KEY_BYTES:
            raise SecretStoreError(_MASTER_KEY_MESSAGE)
        self._key = bytes(material)
        # The store hands over a mutable copy; wipe it once sealed into bytes.
        for index in range(len(material)):
            material[index] = 0
        return self._key


def blob_to_record(blob: SecretBlob) -> dict[str, str]:
    return {
        "alg": blob.alg,
        "nonce": base64.b64encode(blob.nonce).decode("ascii"),
        "ciphertext": base64.b64encode(blob.ciphertext).decode("ascii"),
    }


def blob_from_record(alg: str, nonce: str, ciphertext: str) -> SecretBlob:
    """Decode a stored record, mapping every malformed input to one safe error."""

    try:
        raw_nonce = base64.b64decode(nonce, validate=True)
        raw_ciphertext = base64.b64decode(ciphertext, validate=True)
    except (binascii.Error, ValueError, UnicodeError):
        raise SecretStoreError(_DECRYPT_MESSAGE) from None
    if len(raw_nonce) != NONCE_BYTES or len(raw_ciphertext) < TAG_BYTES:
        raise SecretStoreError(_DECRYPT_MESSAGE)
    return SecretBlob(nonce=raw_nonce, ciphertext=raw_ciphertext, alg=alg)


class InMemoryMasterKeyStore:
    """Test backend: keeps the key in process memory, never touches the platform."""

    def __init__(self, key: bytes | bytearray | None = None) -> None:
        self._key = bytearray(AESGCM.generate_key(bit_length=256) if key is None else key)

    def load_or_create(self) -> bytearray:
        return bytearray(self._key)


class FileMasterKeyStore:
    """POSIX backend: a 0600 file created exclusively, permissions re-checked on read.

    ``create_if_missing=False`` forbids minting a key: a missing file then fails
    closed instead of silently producing a replacement that no saved ciphertext
    can be opened with.
    """

    def __init__(self, path: Path, *, create_if_missing: bool = True) -> None:
        self._path = path
        self._create_if_missing = create_if_missing

    def load_or_create(self) -> bytearray:
        if self._path.exists():
            return self._read()
        if not self._create_if_missing:
            raise SecretStoreError(_MASTER_KEY_MESSAGE)
        key = AESGCM.generate_key(bit_length=256)
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(self._path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            return self._read()
        except OSError:
            raise SecretStoreError(_MASTER_KEY_MESSAGE) from None
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(key)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError:
            self._discard()
            raise SecretStoreError(_MASTER_KEY_MESSAGE) from None
        return bytearray(key)

    def _read(self) -> bytearray:
        mode = self._private_mode()
        if mode != 0o600:
            raise SecretStoreError(_PERMISSION_MESSAGE)
        try:
            raw = self._path.read_bytes()
        except OSError:
            raise SecretStoreError(_MASTER_KEY_MESSAGE) from None
        if len(raw) != MASTER_KEY_BYTES:
            raise SecretStoreError(_MASTER_KEY_MESSAGE)
        return bytearray(raw)

    def _private_mode(self) -> int:
        try:
            mode = stat.S_IMODE(self._path.stat().st_mode)
            if mode == 0o600:
                return mode
            os.chmod(self._path, 0o600)
            return stat.S_IMODE(self._path.stat().st_mode)
        except OSError:
            raise SecretStoreError(_PERMISSION_MESSAGE) from None

    def _discard(self) -> None:
        try:
            self._path.unlink(missing_ok=True)
        except OSError:
            pass


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.c_void_p)]
    # Not a native field: keeps the Python buffer alive while the blob is used.
    _keep_alive: Any


_DPAPI_ENTROPY = b"frame-ai/provider-master-key/v1"
_CRYPTPROTECT_UI_FORBIDDEN = 0x01


def _crypt32() -> Any:
    if sys.platform != "win32":
        raise SecretStoreError(_MASTER_KEY_MESSAGE)
    try:
        return ctypes.WinDLL("crypt32.dll", use_last_error=True)
    except OSError:
        raise SecretStoreError(_MASTER_KEY_MESSAGE) from None


def _kernel32() -> Any:
    if sys.platform != "win32":
        raise SecretStoreError(_MASTER_KEY_MESSAGE)
    try:
        return ctypes.WinDLL("kernel32.dll", use_last_error=True)
    except OSError:
        raise SecretStoreError(_MASTER_KEY_MESSAGE) from None


def _blob_from_bytes(raw: bytes) -> _DataBlob:
    buffer = ctypes.create_string_buffer(raw)
    blob = _DataBlob()
    blob.cbData = len(raw)
    blob.pbData = ctypes.cast(buffer, ctypes.c_void_p)
    blob._keep_alive = buffer
    return blob


def _local_free(pointer: int) -> None:
    kernel32 = _kernel32()
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    kernel32.LocalFree(pointer)


def _bytes_from_blob(blob: _DataBlob) -> bytes:
    if not blob.pbData or not blob.cbData:
        raise SecretStoreError(_MASTER_KEY_MESSAGE)
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    except (ValueError, OSError):
        raise SecretStoreError(_MASTER_KEY_MESSAGE) from None
    finally:
        _local_free(blob.pbData)


def dpapi_protect(raw: bytes) -> bytes:
    """Seal bytes with the current Windows user's DPAPI key (no UI, fixed entropy)."""

    crypt32 = _crypt32()
    data = _blob_from_bytes(raw)
    entropy = _blob_from_bytes(_DPAPI_ENTROPY)
    sealed = _DataBlob()
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.c_wchar_p,
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptProtectData.restype = ctypes.c_int
    ok = crypt32.CryptProtectData(
        ctypes.byref(data),
        None,
        ctypes.byref(entropy),
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(sealed),
    )
    if not ok:
        raise SecretStoreError(_MASTER_KEY_MESSAGE)
    return _bytes_from_blob(sealed)


def dpapi_unprotect(raw: bytes) -> bytes:
    """Open a DPAPI blob; tampering or a different user/machine fails closed."""

    crypt32 = _crypt32()
    data = _blob_from_bytes(raw)
    entropy = _blob_from_bytes(_DPAPI_ENTROPY)
    opened = _DataBlob()
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = ctypes.c_int
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(data),
        None,
        ctypes.byref(entropy),
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(opened),
    )
    if not ok:
        raise SecretStoreError(_MASTER_KEY_MESSAGE)
    return _bytes_from_blob(opened)


class DpapiMasterKeyStore:
    """Windows backend: the key file holds a DPAPI blob, not the key itself.

    ``chmod`` is ineffective on Windows, so protection comes from DPAPI plus the
    user profile ACL -- never from the file mode.

    ``create_if_missing=False`` forbids minting a key, so a deleted key file fails
    closed instead of leaving a misleading replacement on disk.
    """

    def __init__(
        self,
        path: Path,
        *,
        protect: Callable[[bytes], bytes] = dpapi_protect,
        unprotect: Callable[[bytes], bytes] = dpapi_unprotect,
        create_if_missing: bool = True,
    ) -> None:
        self._path = path
        self._protect = protect
        self._unprotect = unprotect
        self._create_if_missing = create_if_missing

    def load_or_create(self) -> bytearray:
        if self._path.exists():
            return self._read()
        if not self._create_if_missing:
            raise SecretStoreError(_MASTER_KEY_MESSAGE)
        key = AESGCM.generate_key(bit_length=256)
        try:
            sealed = self._protect(key)
        except SecretStoreError:
            raise
        except Exception:
            raise SecretStoreError(_MASTER_KEY_MESSAGE) from None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(self._path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            return self._read()
        except OSError:
            raise SecretStoreError(_MASTER_KEY_MESSAGE) from None
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(sealed)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError:
            self._discard()
            raise SecretStoreError(_MASTER_KEY_MESSAGE) from None
        return bytearray(key)

    def _read(self) -> bytearray:
        try:
            sealed = self._path.read_bytes()
        except OSError:
            raise SecretStoreError(_MASTER_KEY_MESSAGE) from None
        try:
            raw = self._unprotect(sealed)
        except SecretStoreError:
            raise
        except Exception:
            raise SecretStoreError(_MASTER_KEY_MESSAGE) from None
        if len(raw) != MASTER_KEY_BYTES:
            raise SecretStoreError(_MASTER_KEY_MESSAGE)
        return bytearray(raw)

    def _discard(self) -> None:
        try:
            self._path.unlink(missing_ok=True)
        except OSError:
            pass


class KeychainBridge(Protocol):
    """Narrow seam over Security.framework so tests never touch a real keychain."""

    def find(self, service: str, account: str) -> bytes | None: ...

    def add(self, service: str, account: str, secret: bytes) -> None: ...


_SEC_ITEM_NOT_FOUND = -25299
_SEC_DUPLICATE_ITEM = -25298


class SecurityFrameworkBridge:
    """macOS Keychain access through ctypes; the secret never enters argv."""

    def __init__(self) -> None:
        self._library = _security_framework()

    def find(self, service: str, account: str) -> bytes | None:
        library = self._library
        service_raw = service.encode("utf-8")
        account_raw = account.encode("utf-8")
        length = ctypes.c_uint32(0)
        data = ctypes.c_void_p()
        library.SecKeychainFindGenericPassword.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_char_p,
            ctypes.c_uint32,
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_void_p,
        ]
        library.SecKeychainFindGenericPassword.restype = ctypes.c_int32
        status = library.SecKeychainFindGenericPassword(
            None,
            len(service_raw),
            service_raw,
            len(account_raw),
            account_raw,
            ctypes.byref(length),
            ctypes.byref(data),
            None,
        )
        if status == _SEC_ITEM_NOT_FOUND:
            return None
        if status != 0:
            raise SecretStoreError(_MASTER_KEY_MESSAGE)
        try:
            if not data.value or not length.value:
                raise SecretStoreError(_MASTER_KEY_MESSAGE)
            return ctypes.string_at(data.value, length.value)
        finally:
            library.SecKeychainItemFreeContent(None, data)

    def add(self, service: str, account: str, secret: bytes) -> None:
        library = self._library
        service_raw = service.encode("utf-8")
        account_raw = account.encode("utf-8")
        library.SecKeychainAddGenericPassword.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_char_p,
            ctypes.c_uint32,
            ctypes.c_char_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        library.SecKeychainAddGenericPassword.restype = ctypes.c_int32
        buffer = ctypes.create_string_buffer(secret)
        status = library.SecKeychainAddGenericPassword(
            None,
            len(service_raw),
            service_raw,
            len(account_raw),
            account_raw,
            len(secret),
            ctypes.cast(buffer, ctypes.c_void_p),
            None,
        )
        if status not in (0, _SEC_DUPLICATE_ITEM):
            raise SecretStoreError(_MASTER_KEY_MESSAGE)


def _security_framework() -> Any:
    if sys.platform != "darwin":
        raise SecretStoreError(_MASTER_KEY_MESSAGE)
    try:
        return ctypes.CDLL("/System/Library/Frameworks/Security.framework/Security")
    except OSError:
        raise SecretStoreError(_MASTER_KEY_MESSAGE) from None


class KeychainMasterKeyStore:
    """macOS backend: the master key is a generic password in the user keychain.

    ``create_if_missing=False`` forbids adding an item, so a deleted keychain entry
    fails closed instead of silently minting a replacement key.
    """

    def __init__(
        self,
        service: str,
        account: str,
        *,
        bridge: KeychainBridge | None = None,
        create_if_missing: bool = True,
    ) -> None:
        self._service = service
        self._account = account
        self._bridge = bridge
        self._create_if_missing = create_if_missing

    def load_or_create(self) -> bytearray:
        bridge = self._bridge if self._bridge is not None else SecurityFrameworkBridge()
        existing = bridge.find(self._service, self._account)
        if existing is not None:
            return self._decode(existing)
        if not self._create_if_missing:
            raise SecretStoreError(_MASTER_KEY_MESSAGE)
        key = AESGCM.generate_key(bit_length=256)
        bridge.add(self._service, self._account, base64.b64encode(key))
        return bytearray(key)

    @staticmethod
    def _decode(raw: bytes) -> bytearray:
        try:
            key = base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError):
            raise SecretStoreError(_MASTER_KEY_MESSAGE) from None
        if len(key) != MASTER_KEY_BYTES:
            raise SecretStoreError(_MASTER_KEY_MESSAGE)
        return bytearray(key)


def default_master_key_store(data_dir: Path, *, allow_create: bool = True) -> MasterKeyStore:
    """Pick the platform backend; the path is only used by Windows/POSIX.

    Platforms outside the supported matrix (Windows/Linux/macOS) deliberately use
    the POSIX file backend: it still enforces 0600 with a chmod re-check and fails
    closed, so there is no plaintext fallback. No platform allow-list is applied.

    ``allow_create=False`` is passed through to every backend so a caller that
    depends on an existing key can refuse to mint a replacement.
    """

    path = data_dir / MASTER_KEY_FILENAME
    if sys.platform == "win32":
        return DpapiMasterKeyStore(path, create_if_missing=allow_create)
    if sys.platform == "darwin":
        return KeychainMasterKeyStore("frame-ai", str(path), create_if_missing=allow_create)
    return FileMasterKeyStore(path, create_if_missing=allow_create)


def write_private_document(path: Path, payload: bytes) -> None:
    """Atomically replace ``path`` with ``payload`` using a 0600 temporary file.

    The temporary file is created with ``os.open(..., 0o600)`` so there is no
    window where the document exists with default permissions. ``os.replace``
    is the only step that touches the destination; on any failure the temporary
    file is removed and the previous document is left byte-for-byte intact.
    """

    temporary = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.unlink(missing_ok=True)
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError:
            temporary.unlink(missing_ok=True)
            raise
        os.replace(temporary, path)
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


__all__ = [
    "ALGORITHM",
    "MASTER_KEY_BYTES",
    "MASTER_KEY_FILENAME",
    "NONCE_BYTES",
    "TAG_BYTES",
    "DpapiMasterKeyStore",
    "FileMasterKeyStore",
    "InMemoryMasterKeyStore",
    "KeychainBridge",
    "KeychainMasterKeyStore",
    "MasterKeyStore",
    "SecretBlob",
    "SecretBox",
    "SecretStoreError",
    "SecurityFrameworkBridge",
    "blob_from_record",
    "blob_to_record",
    "default_master_key_store",
    "dpapi_protect",
    "dpapi_unprotect",
    "provider_settings_aad",
    "write_private_document",
]
