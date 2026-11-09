from __future__ import annotations

from enum import StrEnum


class ConversionMode(StrEnum):
    """How strongly a selected style may reshape the photograph."""

    NATURAL = "natural"
    STYLE = "style"
    CREATIVE = "creative"


__all__ = ["ConversionMode"]
