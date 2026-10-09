"""Bounded retry, retry-budget, idempotency guard, and circuit-breaker primitives.

These are integration primitives only. No production connector uses them until a
connector explicitly opts in and supplies its own timeouts and retryable errors.
"""
from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass
from typing import Callable, TypeVar

T = TypeVar("T")


class CircuitOpenError(RuntimeError):
    """Raised when a dependency circuit is open."""


class RetryBudgetExhausted(RuntimeError):
    """Raised when a shared retry budget has been consumed."""


class NonIdempotentRetryError(RuntimeError):
    """Raised when retries are requested for a non-idempotent operation."""


class TransientConnectorError(ConnectionError):
    """Marker for explicitly retryable connector failures."""


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 0.05
    max_delay_seconds: float = 1.0

    def __post_init__(self) -> None:
        if not 1 <= self.max_attempts <= 5:
            raise ValueError("max_attempts must be between 1 and 5")
        if self.base_delay_seconds < 0 or self.max_delay_seconds < self.base_delay_seconds:
            raise ValueError("Invalid retry delay bounds")


class RetryBudget:
    """Process-local sliding-window retry cap to prevent aggregate retry storms."""

    def __init__(self, max_retries: int = 60, window_seconds: float = 60.0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        if max_retries < 0 or window_seconds <= 0:
            raise ValueError("Invalid retry budget bounds")
        self.max_retries = max_retries
        self.window_seconds = window_seconds
        self.clock = clock
        self._attempts: list[float] = []
        self._lock = threading.Lock()

    def consume(self) -> bool:
        now = self.clock()
        with self._lock:
            self._attempts = [value for value in self._attempts if now - value < self.window_seconds]
            if len(self._attempts) >= self.max_retries:
                return False
            self._attempts.append(now)
            return True


class CircuitBreaker:
    """Thread-safe closed/open/half-open breaker allowing one probe after cooldown."""

    def __init__(self, failure_threshold: int = 3, reset_timeout_seconds: float = 30.0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        if failure_threshold < 1 or reset_timeout_seconds <= 0:
            raise ValueError("Invalid circuit-breaker bounds")
        self.failure_threshold = failure_threshold
        self.reset_timeout_seconds = reset_timeout_seconds
        self.clock = clock
        self._state = "closed"
        self._failures = 0
        self._opened_at = 0.0
        self._probe_in_flight = False
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        with self._lock:
            if self._state == "open" and self.clock() - self._opened_at >= self.reset_timeout_seconds:
                return "half_open"
            return self._state

    def call(self, operation: Callable[[], T]) -> T:
        probe = False
        with self._lock:
            if self._state == "open":
                if self.clock() - self._opened_at < self.reset_timeout_seconds:
                    raise CircuitOpenError("Circuit is open; dependency call rejected")
                self._state = "half_open"
            if self._state == "half_open":
                if self._probe_in_flight:
                    raise CircuitOpenError("Circuit is half-open; probe already in flight")
                self._probe_in_flight = True
                probe = True
        try:
            result = operation()
        except Exception:
            with self._lock:
                self._failures += 1
                self._probe_in_flight = False
                if probe or self._failures >= self.failure_threshold:
                    self._state = "open"
                    self._opened_at = self.clock()
            raise
        with self._lock:
            self._failures = 0
            self._probe_in_flight = False
            self._state = "closed"
        return result


def resilient_call(
    operation: Callable[[], T],
    *,
    policy: RetryPolicy = RetryPolicy(),
    breaker: CircuitBreaker | None = None,
    budget: RetryBudget | None = None,
    idempotent: bool = False,
    retryable: tuple[type[BaseException], ...] = (TransientConnectorError, TimeoutError, ConnectionError),
    sleep: Callable[[float], None] = time.sleep,
    random_value: Callable[[], float] = random.random,
) -> T:
    """Run an operation with bounded exponential backoff; retries require idempotency."""
    if policy.max_attempts > 1 and not idempotent:
        raise NonIdempotentRetryError("Retries require an explicitly idempotent operation")
    def attempts() -> T:
        for attempt in range(1, policy.max_attempts + 1):
            try:
                return operation()
            except retryable:
                if attempt >= policy.max_attempts:
                    raise
                if budget is not None and not budget.consume():
                    raise RetryBudgetExhausted("Shared retry budget exhausted")
                ceiling = min(policy.max_delay_seconds, policy.base_delay_seconds * (2 ** (attempt - 1)))
                sleep(ceiling * (0.5 + max(0.0, min(1.0, random_value())) * 0.5))
        raise RuntimeError("Unreachable retry state")
    return breaker.call(attempts) if breaker is not None else attempts()
