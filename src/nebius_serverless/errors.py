"""Errors for the cloud Jobs client.

They carry identity, never env values or tokens.
"""

from collections.abc import Iterable

_DEFAULT_RECOVERY = (
    "If you have a job id, reload it with jobs.get. "
    "Do not send a second create."
)


class Error(Exception):
    """Base error for the Jobs client."""

    def __init__(
        self,
        message: str,
        *,
        operation: str | None = None,
        project: str | None = None,
        key: str | None = None,
        run_id: str | None = None,
        recovery: str = _DEFAULT_RECOVERY,
        diff: Iterable[object] = (),
    ) -> None:
        super().__init__(message)
        self.operation = operation
        self.project = project
        self.key = key
        self.run_id = run_id
        self.recovery = recovery
        self.diff = tuple(diff)


class ValidationError(Error):
    """The call was rejected before Nebius was contacted."""


class UnsupportedFeature(ValidationError):
    """The call asks for something this slice does not implement."""


class AccessError(Error):
    """Authentication or permission failed."""


class CapacityError(Error):
    """The API rejected the job for quota or capacity."""


class TransportError(Error):
    """The call failed and create was not accepted."""


class SubmissionUncertain(Error):
    """Create may have been accepted and the id is unknown."""


class KeyConflict(Error):
    """The API reports an existing resource and its id is known."""


class WaitTimeout(Error):
    """The local wait ended. The cloud job is unchanged."""
