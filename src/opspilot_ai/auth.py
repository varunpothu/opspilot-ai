"""Fail-closed API token authentication and role-based authorisation.

Configure OPSPILOT_API_TOKEN_HASHES as JSON mapping SHA-256(token) to
{"role": "viewer|operator|approver|admin", "actor": "stable-human-or-service-id"}.
Raw bearer tokens are never stored in this configuration. Use an identity provider
for production; this static token map is a local MVP integration seam.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_ROLE_PERMISSIONS = {
    "viewer": {"read"},
    "operator": {"read", "run", "request_approval"},
    "approver": {"read", "decide_approval"},
    "admin": {"read", "run", "request_approval", "decide_approval", "admin"},
}
_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    actor: str
    role: str
    permissions: frozenset[str]


def _token_records() -> dict[str, dict[str, str]]:
    raw = os.getenv("OPSPILOT_API_TOKEN_HASHES", "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=503, detail="API token configuration is invalid") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=503, detail="API token configuration must be a JSON object")
    records: dict[str, dict[str, str]] = {}
    for digest, value in parsed.items():
        if not isinstance(digest, str) or len(digest) != 64 or not isinstance(value, dict):
            raise HTTPException(status_code=503, detail="API token configuration has an invalid entry")
        role = value.get("role")
        actor = value.get("actor")
        if not isinstance(role, str) or role not in _ROLE_PERMISSIONS or not isinstance(actor, str) or not actor.strip():
            raise HTTPException(status_code=503, detail="API token configuration has an invalid role or actor")
        records[digest.lower()] = {"role": role, "actor": actor.strip()}
    return records


def authenticate(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> Principal:
    """Authenticate bearer token, with an explicit opt-in local-development bypass."""
    if os.getenv("OPSPILOT_AUTH_MODE", "required").lower() == "disabled":
        return Principal(actor="local-development", role="admin", permissions=frozenset(_ROLE_PERMISSIONS["admin"]))
    records = _token_records()
    if not records:
        raise HTTPException(status_code=503, detail="Authentication is required but no API tokens are configured")
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Bearer token required", headers={"WWW-Authenticate": "Bearer"})
    digest = hashlib.sha256(credentials.credentials.encode("utf-8")).hexdigest()
    matched = next((value for key, value in records.items() if hmac.compare_digest(key, digest)), None)
    if matched is None:
        raise HTTPException(status_code=401, detail="Invalid bearer token", headers={"WWW-Authenticate": "Bearer"})
    return Principal(
        actor=matched["actor"],
        role=matched["role"],
        permissions=frozenset(_ROLE_PERMISSIONS[matched["role"]]),
    )


def require_permission(permission: str):
    def dependency(principal: Principal = Depends(authenticate)) -> Principal:
        if permission not in principal.permissions:
            raise HTTPException(status_code=403, detail="Insufficient role for this operation")
        return principal
    return dependency


def require_any_permission(*permissions: str):
    def dependency(principal: Principal = Depends(authenticate)) -> Principal:
        if not any(permission in principal.permissions for permission in permissions):
            raise HTTPException(status_code=403, detail="Insufficient role for this operation")
        return principal
    return dependency
