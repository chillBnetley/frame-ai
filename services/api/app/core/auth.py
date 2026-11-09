from __future__ import annotations

import getpass
import logging
import os
import secrets
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("frame_ai.auth")

API_TOKEN_BYTES = 32
API_TOKEN_HEX_CHARS = API_TOKEN_BYTES * 2
API_TOKEN_FILENAME = "api-token"


class ApiTokenService:
    """Owns the local API token file and compares presented tokens.

    The token is 64 lowercase hex characters (32 random bytes) and is rotated
    on every startup. Only this service and the file on disk ever hold it; it is
    never logged or serialized into OpenAPI.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._token: str | None = None

    @property
    def path(self) -> Path:
        return self._path

    def ensure_token(self) -> str:
        token = secrets.token_hex(API_TOKEN_BYTES)
        _write_token(self._path, token)
        self._token = token
        return token

    def matches(self, provided: str | None) -> bool:
        token = self._token
        if token is None or not provided or not provided.isascii():
            return False
        return secrets.compare_digest(provided, token)


def _write_token(path: Path, token: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.unlink(missing_ok=True)
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="ascii", newline="\n") as handle:
                handle.write(token)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError:
            temporary.unlink(missing_ok=True)
            raise
        _grant_replace_access(path)
        os.replace(temporary, path)
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    _harden_windows_acl(path)


def _grant_replace_access(path: Path) -> None:
    """Let the current user delete the previous token file on Windows.

    ``icacls /grant:r user:(R,W)`` (the hardening applied after the first
    rotation) does not include the delete right, so the next ``os.replace``
    fails with WinError 5. Grant delete on the existing file before replacing.
    """

    if sys.platform != "win32" or not path.exists():
        return
    user = os.environ.get("USERNAME") or getpass.getuser()
    if not user:
        return
    try:
        subprocess.run(
            ["icacls", str(path), "/grant:r", f"{user}:(R,W,D)"],
            check=False,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        logger.warning("api_token_replace_acl_failed")


def _harden_windows_acl(path: Path) -> None:
    """Best effort: replace inherited Windows ACL with a current-user entry."""

    if sys.platform != "win32":
        return
    user = os.environ.get("USERNAME") or getpass.getuser()
    if not user:
        return
    try:
        subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:(R,W,D)"],
            check=False,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        logger.warning("api_token_acl_failed")


__all__ = [
    "API_TOKEN_BYTES",
    "API_TOKEN_FILENAME",
    "API_TOKEN_HEX_CHARS",
    "ApiTokenService",
]
