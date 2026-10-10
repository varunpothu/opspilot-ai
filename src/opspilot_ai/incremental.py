"""Watermark-driven incremental sync orchestration with replay-safe commit ordering."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable

from .sync_state import SyncStateStore, WatermarkRegression, _compare_watermarks, _validate_watermark


class IncrementalSyncError(RuntimeError):
    """The incremental sync contract could not be satisfied safely."""


@dataclass(frozen=True)
class IncrementalSyncOutcome:
    resource_key: str
    status: str
    lower_bound: int | float | str | None
    upper_bound: int | float | str | None
    rows_written: int
    checkpoint_revision: int | None
    etag: str | None
    last_modified: str | None


class IncrementalSyncRunner:
    """Coordinate source reads, an idempotent sink commit, and checkpoint advancement.

    The caller owns source and destination transactions. The write_batch callback
    must commit atomically and be idempotent by business key because a process can
    crash after the sink commits but before the checkpoint commits.
    """

    def __init__(self, state: SyncStateStore, *, max_batch_rows: int = 10_000):
        if max_batch_rows < 1:
            raise ValueError("max_batch_rows must be positive")
        self.state = state
        self.max_batch_rows = max_batch_rows

    def run(
        self,
        resource_key: str,
        *,
        get_high_watermark: Callable[[], int | float | str | None],
        read_changes: Callable[[int | float | str | None, int | float | str], Iterable[Any]],
        write_batch: Callable[[list[Any]], None],
        sink_idempotent: bool,
        overlap: timedelta = timedelta(0),
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> IncrementalSyncOutcome:
        if not sink_idempotent:
            raise IncrementalSyncError("sink must be idempotent before incremental sync can run")
        if overlap < timedelta(0):
            raise ValueError("overlap cannot be negative")
        checkpoint = self.state.get_checkpoint(resource_key)
        previous = checkpoint["watermark"] if checkpoint else None
        revision = checkpoint["revision"] if checkpoint else None
        upper = get_high_watermark()
        if upper is None:
            return IncrementalSyncOutcome(
                resource_key, "no_source_watermark", previous, None, 0, revision, etag, last_modified,
            )
        _validate_watermark(upper)
        if previous is not None:
            if _compare_watermarks(upper, previous) < 0:
                raise WatermarkRegression("source high watermark is behind the committed checkpoint")
            if overlap and not isinstance(previous, str):
                raise IncrementalSyncError("overlap windows require ISO-8601 timestamp watermarks")
        lower = _overlap_lower_bound(previous, overlap) if previous is not None else None
        rows = list(read_changes(lower, upper))
        if len(rows) > self.max_batch_rows:
            raise IncrementalSyncError(
                f"batch exceeded {self.max_batch_rows} rows; paginate or chunk the source read"
            )
        # Do not move the checkpoint until the destination callback has returned
        # successfully. The callback contract requires an atomic, idempotent commit.
        write_batch(rows)
        committed = self.state.commit_checkpoint(
            resource_key, upper, expected_revision=revision, etag=etag, last_modified=last_modified,
        )
        return IncrementalSyncOutcome(
            resource_key=resource_key,
            status="completed",
            lower_bound=lower,
            upper_bound=upper,
            rows_written=len(rows),
            checkpoint_revision=committed["revision"],
            etag=etag,
            last_modified=last_modified,
        )


def _overlap_lower_bound(value: int | float | str, overlap: timedelta) -> int | float | str:
    if overlap == timedelta(0):
        return value
    if not isinstance(value, str):
        raise IncrementalSyncError("overlap windows require ISO-8601 timestamp watermarks")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (parsed.astimezone(timezone.utc) - overlap).isoformat()
