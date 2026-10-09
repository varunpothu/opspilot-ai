"""Human approval workflow for review-only remediation plans; never executes actions."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .audit import verify_audit_chain


class ApprovalError(ValueError):
    """Approval workflow validation or state error."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure(db_path: str | Path) -> Path:
    path = Path(db_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS approval_requests (
                approval_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                requested_by TEXT NOT NULL,
                reason TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                decided_by TEXT,
                decision_reason TEXT,
                decided_at TEXT,
                audit_events_json TEXT NOT NULL
            )
        """)
    return path


def _append_event(events: list[dict[str, Any]], payload: dict[str, Any]) -> list[dict[str, Any]]:
    previous = events[-1]["event_hash"] if events else "0" * 64
    body = {"sequence": len(events), "previous_hash": previous, **payload}
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return [*events, {**body, "event_hash": digest}]


def _row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "approval_id": row[0], "run_id": row[1], "requested_by": row[2],
        "reason": row[3], "status": row[4], "created_at": row[5], "expires_at": row[6],
        "decided_by": row[7], "decision_reason": row[8], "decided_at": row[9],
        "audit_events": json.loads(row[10]),
        "execution_performed": False,
        "scope": "review_only_no_execution",
    }


_COLUMNS = "approval_id, run_id, requested_by, reason, status, created_at, expires_at, decided_by, decision_reason, decided_at, audit_events_json"


def create_approval(db_path: str | Path, run_id: str, requester: str, reason: str, run_result: Any) -> dict[str, Any]:
    if not reason.strip() or len(reason.strip()) < 8 or len(reason) > 1000:
        raise ApprovalError("Approval reason must contain 8 to 1000 characters")
    if run_result is None:
        raise ApprovalError("Run not found")
    verification = verify_audit_chain(run_result.audit_chain)
    if not verification["valid"]:
        raise ApprovalError("Run audit chain failed verification; approval request denied")
    path = _ensure(db_path)
    approval_id = str(uuid4())
    now = _now()
    expiry = now + timedelta(minutes=30)
    events = _append_event([], {
        "event_type": "approval_requested", "approval_id": approval_id, "run_id": run_id,
        "actor": requester, "reason": reason.strip(), "timestamp": now.isoformat(),
        "audit_head_hash": verification["head_hash"],
    })
    with sqlite3.connect(path) as conn:
        conn.execute(
            f"INSERT INTO approval_requests ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?)",
            (approval_id, run_id, requester, reason.strip(), "pending", now.isoformat(), expiry.isoformat(),
             json.dumps(events, sort_keys=True)),
        )
    return get_approval(db_path, approval_id)  # type: ignore[return-value]


def decide_approval(db_path: str | Path, approval_id: str, approver: str, decision: str, reason: str) -> dict[str, Any]:
    if decision not in {"approved", "rejected"}:
        raise ApprovalError("Decision must be approved or rejected")
    if not reason.strip() or len(reason.strip()) < 8 or len(reason) > 1000:
        raise ApprovalError("Decision reason must contain 8 to 1000 characters")
    path = _ensure(db_path)
    with sqlite3.connect(path, timeout=10, isolation_level=None) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(f"SELECT {_COLUMNS} FROM approval_requests WHERE approval_id=?", (approval_id,)).fetchone()
        if row is None:
            conn.execute("ROLLBACK")
            raise ApprovalError("Approval request not found")
        current = _row(row)
        if current["status"] != "pending":
            conn.execute("ROLLBACK")
            raise ApprovalError("Approval request is no longer pending")
        if current["requested_by"] == approver:
            conn.execute("ROLLBACK")
            raise ApprovalError("Separation of duties: requester cannot approve their own request")
        if _now() >= datetime.fromisoformat(current["expires_at"]):
            events = _append_event(current["audit_events"], {
                "event_type": "approval_expired", "approval_id": approval_id,
                "actor": approver, "timestamp": _now().isoformat(),
            })
            conn.execute(
                "UPDATE approval_requests SET status='expired', audit_events_json=? WHERE approval_id=?",
                (json.dumps(events, sort_keys=True), approval_id),
            )
            conn.execute("COMMIT")
            raise ApprovalError("Approval request has expired")
        now = _now()
        events = _append_event(current["audit_events"], {
            "event_type": "approval_decided", "approval_id": approval_id, "actor": approver,
            "decision": decision, "reason": reason.strip(), "timestamp": now.isoformat(),
        })
        conn.execute(
            "UPDATE approval_requests SET status=?, decided_by=?, decision_reason=?, decided_at=?, audit_events_json=? WHERE approval_id=? AND status='pending'",
            (decision, approver, reason.strip(), now.isoformat(), json.dumps(events, sort_keys=True), approval_id),
        )
        conn.execute("COMMIT")
    return get_approval(db_path, approval_id)  # type: ignore[return-value]


def get_approval(db_path: str | Path, approval_id: str) -> dict[str, Any] | None:
    path = _ensure(db_path)
    with sqlite3.connect(path) as conn:
        row = conn.execute(f"SELECT {_COLUMNS} FROM approval_requests WHERE approval_id=?", (approval_id,)).fetchone()
    return _row(row) if row else None


def verify_approval_events(approval: dict[str, Any]) -> dict[str, Any]:
    events = approval["audit_events"]
    previous = "0" * 64
    errors: list[str] = []
    for index, event in enumerate(events):
        body = {key: value for key, value in event.items() if key != "event_hash"}
        if event.get("sequence") != index or event.get("previous_hash") != previous:
            errors.append(f"chain_link_mismatch:{index}")
        expected = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if event.get("event_hash") != expected:
            errors.append(f"event_hash_mismatch:{index}")
        previous = str(event.get("event_hash", ""))
    return {"valid": bool(events) and not errors, "event_count": len(events), "head_hash": previous, "errors": errors}
