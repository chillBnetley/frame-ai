from __future__ import annotations

from collections.abc import Iterable
from typing import Any, TypeAlias

FieldIssue: TypeAlias = tuple[str, str, str]
# (field name, rule, human message) for a service-side validation failure.


class AppError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}
        self.headers = headers or {}


def field_error_details(issues: Iterable[FieldIssue]) -> dict[str, Any]:
    """Build ``details.fields`` in the same shape the request validator emits.

    Keeping service-side and framework-side 422 payloads identical is what lets
    one frontend parser handle both.
    """
    unique: dict[str, dict[str, Any]] = {}
    for name, rule, message in issues:
        unique.setdefault(
            name,
            {"field": name, "rule": rule, "limit": {}, "message": message},
        )
    return {"fields": list(unique.values())}


def field_names(issues: Iterable[FieldIssue]) -> list[str]:
    return list(dict.fromkeys(name for name, _, _ in issues))
