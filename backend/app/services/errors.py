"""In-memory error ring buffer (NEXUS 2.1).

Keeps the last N errors (timestamp + message + context) for the
GET /api/v1/system/errors endpoint. In-memory on purpose: it is
observability for the running process, not an audit log — persistent
history lives in monitoring_events. Thread-safe.
"""

import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any

MAX_ERRORS = 100

_buffer: deque[dict[str, Any]] = deque(maxlen=MAX_ERRORS)
_lock = threading.Lock()


def record_error(message: str, context: str | None = None) -> None:
    """Append an error to the ring buffer (drops the oldest past 100)."""
    with _lock:
        _buffer.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "message": message,
                "context": context,
            }
        )


def get_errors() -> list[dict[str, Any]]:
    """Return buffered errors, latest first."""
    with _lock:
        return list(reversed(_buffer))


def clear_errors() -> None:
    """Empty the buffer (tests only)."""
    with _lock:
        _buffer.clear()
