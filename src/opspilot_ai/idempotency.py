"""SQLite-backed idempotency reservations for API operations."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class IdempotencyConflict(ValueError):
    """Raised when a key is reused with a different request or still processing."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure(db_path: str | Path) -> Path:
    path = Path(db_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS idempotency_records (
                key_hash TEXT PRIMARY KEY,
                request_hash TEXT NOT NULL,
                state TEXT NOT NULL,
                response_json TEXT,
                created_at TEXT NOT NULL
            )
        """)
    return path


def reserve(db_path: str | Path, key: str, request_payload: dict[str, Any]) -> dict[str, Any]:
    if not 8 <= len(key) <= 200:
        raise IdempotencyConflict("Idempotency-Key must contain 8 to 200 characters")
    path = _ensure(db_path)
    key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
    request_hash = hashlib.sha256(json.dumps(request_payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    with sqlite3.connect(path, timeout=10, isolation_level=None) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT request_hash, state, response_json FROM idempotency_records WHERE key_hash = ?",
            (key_hash,),
        ).fetchone()
        if row:
            if row[0] != request_hash:
                conn.execute("ROLLBACK")
                raise IdempotencyConflict("Idempotency-Key was already used with a different request")
            if row[1] == "completed" and row[2]:
                conn.execute("COMMIT")
                return {"state": "replay", "response": json.loads(row[2])}
            conn.execute("ROLLBACK")
            raise IdempotencyConflict("An operation with this Idempotency-Key is already in progress")
        conn.execute(
            "INSERT INTO idempotency_records(key_hash, request_hash, state, response_json, created_at) VALUES (?, ?, 'processing', NULL, ?)",
            (key_hash, request_hash, _now()),
        )
        conn.execute("COMMIT")
    return {"state": "reserved", "key_hash": key_hash, "request_hash": request_hash}


def complete(db_path: str | Path, reservation: dict[str, Any], response: dict[str, Any]) -> None:
    path = _ensure(db_path)
    rendered = json.dumps(response, sort_keys=True, separators=(",", ":"), default=str)
    with sqlite3.connect(path, timeout=10) as conn:
        updated = conn.execute(
            "UPDATE idempotency_records SET state='completed', response_json=? WHERE key_hash=? AND request_hash=? AND state='processing'",
            (rendered, reservation["key_hash"], reservation["request_hash"]),
        ).rowcount
        if updated != 1:
            raise IdempotencyConflict("Idempotency reservation could not be completed")


def release(db_path: str | Path, reservation: dict[str, Any]) -> None:
    path = _ensure(db_path)
    with sqlite3.connect(path, timeout=10) as conn:
        conn.execute(
            "DELETE FROM idempotency_records WHERE key_hash=? AND request_hash=? AND state='processing'",
            (reservation["key_hash"], reservation["request_hash"]),
        )
