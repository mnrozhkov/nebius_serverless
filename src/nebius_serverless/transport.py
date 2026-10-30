"""Create, get, and cancel behind a small transport object."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from .errors import (
    AccessError,
    CapacityError,
    Error,
    KeyConflict,
    SubmissionUncertain,
    TransportError,
    exposed_request_id,
)


@dataclass(frozen=True)
class CreateResult:
    """What one create call did, without a second attempt."""

    resource_id: str | None = None
    accepted: bool = False
    state: str | None = None
    failure: str | None = None
    conflict_id: str | None = None
    request_id: str | None = None


class Transport(Protocol):
    """The calls the client makes after a recipe is valid."""

    def create(self, body: Mapping[str, object]) -> CreateResult:
        """Send one create. Do not retry."""

    def get(self, job_id: str) -> dict[str, object]:
        """Fetch one job."""

    def cancel(self, job_id: str) -> dict[str, object]:
        """Request cancellation once."""


def finish_create(result: CreateResult) -> str:
    """Return the job id, or raise the error this result stands for.

    A lost id raises ``SubmissionUncertain`` and does not create again.
    The caller invokes the transport once.
    """
    failure = result.failure
    request_id = result.request_id
    if failure == "access":
        raise AccessError(
            "Authentication or permission failed.",
            operation="create",
            request_id=request_id,
        )
    if failure == "capacity":
        raise CapacityError(
            "The API rejected the job for quota or capacity.",
            operation="create",
            request_id=request_id,
        )
    if failure == "conflict":
        if result.conflict_id:
            raise KeyConflict(
                "The API reports an existing resource for this create.",
                operation="create",
                run_id=result.conflict_id,
                request_id=request_id,
            )
        raise SubmissionUncertain(
            "Create may have been accepted and the id is unknown.",
            operation="create",
            request_id=request_id,
        )
    if failure == "transport":
        raise TransportError(
            "The call failed before create was accepted.",
            operation="create",
            request_id=request_id,
        )
    lost = result.accepted and not result.resource_id
    if failure == "uncertain" or lost:
        raise SubmissionUncertain(
            "Create may have been accepted and the id is unknown.",
            operation="create",
            request_id=request_id,
        )
    if not result.resource_id:
        raise TransportError(
            "The call failed before create was accepted.",
            operation="create",
            request_id=request_id,
        )
    return result.resource_id


def call_transport(
    transport: Transport,
    body: Mapping[str, object],
) -> CreateResult:
    """Create once and map the outcome. Unexpected errors are not retries."""
    try:
        result = transport.create(body)
    except Error:
        raise
    except Exception as exc:
        raise TransportError(
            "The call failed before create was accepted.",
            operation="create",
            request_id=exposed_request_id(exc),
        ) from None
    finish_create(result)
    return result
