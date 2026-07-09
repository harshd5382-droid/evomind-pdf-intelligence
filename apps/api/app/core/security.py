"""Optional API-key authentication.

Auth is OFF by default (`auth_enabled=false`) so local development and the test
suite need no credentials. When enabled, protected endpoints require a key —
supplied either as `Authorization: Bearer <key>` or `X-API-Key: <key>` — that
appears in the comma-separated `api_keys` setting.

Usage:

    from app.core.security import require_api_key

    @router.delete("/documents/{doc_id}", dependencies=[Depends(require_api_key)])
    def delete_document(...): ...
"""
from __future__ import annotations

import hmac

from fastapi import Header, HTTPException

from app.core.config import get_settings


def _extract_key(authorization: str | None, x_api_key: str | None) -> str | None:
    if x_api_key:
        return x_api_key.strip()
    if authorization:
        parts = authorization.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip()
        return authorization.strip()
    return None


def require_api_key(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    """FastAPI dependency. No-op when auth is disabled; otherwise 401s unless a
    valid key is presented."""
    settings = get_settings()
    if not settings.auth_enabled:
        return

    allowed = settings.api_key_set
    if not allowed:
        # Auth was switched on but no keys configured — fail closed so the
        # operator notices, rather than silently allowing everything.
        raise HTTPException(
            status_code=503,
            detail="auth_enabled is true but no api_keys are configured",
        )

    key = _extract_key(authorization, x_api_key)
    # Constant-time compare against every configured key. A plain `key in allowed`
    # short-circuits and leaks timing about how many leading characters matched,
    # which can help an attacker recover a valid key byte-by-byte.
    if not key or not any(hmac.compare_digest(key, a) for a in allowed):
        raise HTTPException(
            status_code=401,
            detail="missing or invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
