"""Single-slot latch holding a fixed payload between detection and expiry instants."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from n225m_bt.components import component


@component(
    id="event_latch",
    kind="feature",
    summary="Holds a fixed payload with a detection and expiry instant until invalidated or consumed",
    tags=["event", "latch", "expiry", "state"],
    uses=[],
)
class EventLatch:
    """Single-slot latch for a fixed candidate payload bounded by detection and expiry instants.

    Arm with set(payload, detected_at, expires_at); the payload and its instants are
    frozen until explicitly cleared. expire_if_due(now) clears the latch once now
    strictly exceeds expires_at and reports whether it just expired, so callers can
    invalidate a stale candidate before acting on the current bar. consume() clears
    the latch immediately, e.g. once a caller is done reacting to the payload. The
    latch holds no logic beyond presence and expiry bookkeeping; it never re-derives
    or updates the payload it holds.
    """

    def __init__(self) -> None:
        self._payload: Any | None = None
        self._detected_at: datetime | None = None
        self._expires_at: datetime | None = None

    @property
    def payload(self) -> Any | None:
        return self._payload

    @property
    def detected_at(self) -> datetime | None:
        return self._detected_at

    @property
    def expires_at(self) -> datetime | None:
        return self._expires_at

    @property
    def is_armed(self) -> bool:
        return self._payload is not None

    def set(self, payload: Any, detected_at: datetime, expires_at: datetime) -> None:
        """Arm the latch with a fixed payload valid over [detected_at, expires_at]."""
        if expires_at < detected_at:
            raise ValueError("expires_at must not precede detected_at")
        self._payload = payload
        self._detected_at = detected_at
        self._expires_at = expires_at

    def expire_if_due(self, now: datetime) -> bool:
        """Clear the latch if now strictly exceeds expires_at; return True if it just expired."""
        if self._payload is not None and self._expires_at is not None and now > self._expires_at:
            self.consume()
            return True
        return False

    def consume(self) -> None:
        """Clear the latch immediately, discarding the payload and its instants."""
        self._payload = None
        self._detected_at = None
        self._expires_at = None
