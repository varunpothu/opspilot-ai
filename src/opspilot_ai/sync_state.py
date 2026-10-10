"""Durable ETag cache and optimistic, monotonic incremental-sync checkpoints.

ETag cache state and ingestion watermarks are deliberately separate: a fetched
HTTP representation may be cached before downstream processing succeeds, but a
watermark must only be advanced after the sink transaction has committed.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class CheckpointConflict(RuntimeError):
    """A concurrent worker changed the checkpoint after it was read."""


class WatermarkRegression(ValueError):
    """A proposed watermark is older than the committed watermark."""


def _connect(path: str | Path) -> sqlite3.Connection:
    database = Path(path).resolve()
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database, timeout=10, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 10000")
    connection.execute("""
        CREATE TABLE IF NOT EXISTS http_representation_cache (
            resource_key TEXT PRIMARY KEY,
            etag TEXT,
            last_modified TEXT,
            content_type TEXT,
            body BLOB NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS sync_checkpoints (
            resource_key TEXT PRIMARY KEY,
            watermark_json TEXT,
            etag TEXT,
            last_modified TEXT,
            revision INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    return connection


class SyncStateStore:
    """SQLite-backed HTTP representation cache and compare-and-swap checkpoints."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path).resolve()
        with _connect(self.db_path):
            pass

    def get_cached_representation(self, resource_key: str) -> dict[str, Any] | None:
        with _connect(self.db_path) as conn:
            row = conn.execute(
                """SELECT etag, last_modified, content_type, body, updated_at
                   FROM http_representation_cache WHERE resource_key = ?""",
                (resource_key,),
            ).fetchone()
        if row is None:
            return None
        return {
            "etag": row["etag"],
            "last_modified": row["last_modified"],
            "content_type": row["content_type"],
            "body": bytes(row["body"]),
            "updated_at": row["updated_at"],
        }

    def put_cached_representation(
        self, resource_key: str, *, etag: str | None, last_modified: str | None,
        content_type: str | None, body: bytes,
    ) -> None:
        if not resource_key or len(resource_key) > 2048:
            raise ValueError("resource_key must contain 1 to 2048 characters")
        if not isinstance(body, bytes):
            raise TypeError("cached HTTP body must be bytes")
        now = datetime.now(timezone.utc).isoformat()
        with _connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO http_representation_cache
                   (resource_key, etag, last_modified, content_type, body, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(resource_key) DO UPDATE SET
                     etag=excluded.etag, last_modified=excluded.last_modified,
                     content_type=excluded.content_type, body=excluded.body,
                     updated_at=excluded.updated_at""",
                (resource_key, etag, last_modified, content_type, sqlite3.Binary(body), now),
            )

    def get_checkpoint(self, resource_key: str) -> dict[str, Any] | None:
        with _connect(self.db_path) as conn:
            row = conn.execute(
                """SELECT watermark_json, etag, last_modified, revision, updated_at
                   FROM sync_checkpoints WHERE resource_key = ?""",
                (resource_key,),
            ).fetchone()
        if row is None:
            return None
        return {
            "resource_key": resource_key,
            "watermark": json.loads(row["watermark_json"]) if row["watermark_json"] is not None else None,
            "etag": row["etag"],
            "last_modified": row["last_modified"],
            "revision": row["revision"],
            "updated_at": row["updated_at"],
        }

    def commit_checkpoint(
        self, resource_key: str, watermark: int | float | str, *,
        expected_revision: int | None, etag: str | None = None,
        last_modified: str | None = None,
    ) -> dict[str, Any]:
        """Advance a watermark with compare-and-swap after the sink has committed.

        Watermarks may be numeric (integers/floats) or ISO-8601 timestamps. An
        opaque cursor is not accepted as a watermark because its ordering cannot
        be proven; store opaque pagination cursors separately in a future adapter.
        """
        if not resource_key or len(resource_key) > 2048:
            raise ValueError("resource_key must contain 1 to 2048 characters")
        _validate_watermark(watermark)
        now = datetime.now(timezone.utc).isoformat()
        encoded = json.dumps(watermark, separators=(",", ":"), ensure_ascii=False)
        conn = _connect(self.db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT watermark_json, revision FROM sync_checkpoints WHERE resource_key = ?",
                (resource_key,),
            ).fetchone()
            actual_revision = row["revision"] if row else None
            if actual_revision != expected_revision:
                raise CheckpointConflict(
                    f"checkpoint revision changed: expected {expected_revision}, found {actual_revision}"
                )
            if row is not None:
                current = json.loads(row["watermark_json"]) if row["watermark_json"] is not None else None
                if current is not None and _compare_watermarks(watermark, current) < 0:
                    raise WatermarkRegression("watermark cannot move backwards")
                revision = row["revision"] + 1
                conn.execute(
                    """UPDATE sync_checkpoints SET watermark_json=?, etag=?, last_modified=?,
                       revision=?, updated_at=? WHERE resource_key=?""",
                    (encoded, etag, last_modified, revision, now, resource_key),
                )
            else:
                revision = 1
                conn.execute(
                    """INSERT INTO sync_checkpoints
                       (resource_key, watermark_json, etag, last_modified, revision, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (resource_key, encoded, etag, last_modified, revision, now),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return self.get_checkpoint(resource_key) or {}


def _validate_watermark(value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError("watermark must be an integer, float, or ISO-8601 timestamp string")
    if isinstance(value, float) and not (value == value and abs(value) != float("inf")):
        raise ValueError("watermark must be finite")
    if isinstance(value, str):
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("string watermark must be an ISO-8601 timestamp") from exc


def _compare_watermarks(new: int | float | str, old: int | float | str) -> int:
    if isinstance(new, str) != isinstance(old, str):
        raise TypeError("watermark type cannot change after a checkpoint is established")
    if isinstance(new, str) and isinstance(old, str):
        def parse(value: str) -> datetime:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        left, right = parse(new), parse(old)
    else:
        left, right = new, old
    return (left > right) - (left < right)
