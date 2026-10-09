"""Run lifecycle contracts with explicit, fail-closed transitions."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import StrEnum
from uuid import uuid4


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    NEEDS_APPROVAL = "needs_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


_ALLOWED: dict[RunStatus, set[RunStatus]] = {
    RunStatus.QUEUED: {RunStatus.RUNNING, RunStatus.CANCELLED, RunStatus.FAILED},
    RunStatus.RUNNING: {RunStatus.NEEDS_APPROVAL, RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED},
    RunStatus.NEEDS_APPROVAL: {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED},
    RunStatus.SUCCEEDED: set(),
    RunStatus.FAILED: set(),
    RunStatus.CANCELLED: set(),
}


@dataclass
class RunEvent:
    event_id: str
    run_id: str
    previous_status: RunStatus | None
    status: RunStatus
    message: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, str | None]:
        return {
            "event_id": self.event_id,
            "run_id": self.run_id,
            "previous_status": self.previous_status.value if self.previous_status else None,
            "status": self.status.value,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class RunLifecycle:
    """Small synchronous state machine; illegal transitions are rejected."""
    run_id: str = field(default_factory=lambda: str(uuid4()))
    status: RunStatus = RunStatus.QUEUED
    events: list[RunEvent] = field(default_factory=list)

    def transition(self, status: RunStatus, message: str) -> RunEvent:
        if status not in _ALLOWED[self.status]:
            raise ValueError(f"Illegal run transition: {self.status.value} -> {status.value}")
        event = RunEvent(
            event_id=str(uuid4()),
            run_id=self.run_id,
            previous_status=self.status,
            status=status,
            message=message,
        )
        self.status = status
        self.events.append(event)
        return event
