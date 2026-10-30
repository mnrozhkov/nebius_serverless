"""One progress fact. Building it does not render or log."""

from dataclasses import dataclass
from typing import Literal

Kind = Literal[
    "submitted",
    "snapshot",
    "transition",
    "terminal",
    "cancel_accepted",
    "local_timeout",
]


@dataclass(frozen=True)
class Status:
    """A job-progress fact with no I/O and no subclass per event.

    ``kind`` is one of ``submitted``, ``snapshot``, ``transition``,
    ``terminal``, ``cancel_accepted``, or ``local_timeout``.
    """

    kind: Kind
    job_id: str = ""
    name: str = ""
    state: str | None = None
    previous: str | None = None
    observed_seconds: float | None = None
    message: str | None = None
    request_id: str | None = None
    attempt: int | None = None
    duration_ms: int | None = None
