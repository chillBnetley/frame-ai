from __future__ import annotations

from dataclasses import dataclass

LOCAL_OWNER_ID = "local"


@dataclass(frozen=True, slots=True)
class OwnerScope:
    """The authenticated owner a request may read or write.

    The current product is a single-user local deployment, so the scope is a
    constant. It is resolved on the server (never from a request header or
    body) so every personal-style query carries an owner predicate and a future
    multi-user identity layer only has to replace this resolver.
    """

    owner_id: str


__all__ = ["LOCAL_OWNER_ID", "OwnerScope"]
