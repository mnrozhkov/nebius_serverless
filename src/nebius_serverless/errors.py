"""Errors for the cloud Jobs client.

They carry identity, never env values or tokens. ``code`` is an SDK
category, not a backend reason code. ``request_id`` is set only when
the Nebius exception already exposes one.
"""

from collections.abc import Iterable

_DEFAULT_RECOVERY = (
    "If you have a job id, reload it with jobs.get. "
    "Do not send a second create."
)
_ACCESS_RECOVERY = (
    "Check the Nebius profile and the project permissions, then retry."
)
_CAPACITY_RECOVERY = "Free quota or capacity, then retry the call."
_CONFLICT_RECOVERY = (
    "Reload the existing job with jobs.get. "
    "Do not send a second create."
)
_WAIT_RECOVERY = "Reload it with jobs.get(id), or call cancel."


class Error(Exception):
    """Base error for the Jobs client."""

    code = "error"
    _recovery = _DEFAULT_RECOVERY

    def __init__(
        self,
        message: str,
        *,
        operation: str | None = None,
        project: str | None = None,
        key: str | None = None,
        run_id: str | None = None,
        recovery: str | None = None,
        diff: Iterable[object] = (),
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.operation = operation
        self.project = project
        self.key = key
        self.run_id = run_id
        self.recovery = self._recovery if recovery is None else recovery
        self.diff = tuple(diff)
        self.request_id = _clean_request_id(request_id)
        self.code = type(self).code


class ValidationError(Error):
    """The call was rejected before Nebius was contacted."""

    code = "validation"


class UnsupportedFeature(ValidationError):
    """The call asks for something this slice does not implement."""

    code = "unsupported"


class AccessError(Error):
    """Authentication or permission failed."""

    code = "access"
    _recovery = _ACCESS_RECOVERY


class CapacityError(Error):
    """The API rejected the job for quota or capacity."""

    code = "capacity"
    _recovery = _CAPACITY_RECOVERY


class TransportError(Error):
    """The call failed and create was not accepted."""

    code = "transport"


class SubmissionUncertain(Error):
    """The outcome of create is unknown.

    The client does not send a second create, does not call
    get-by-name, and does not pick a job from a list.
    """

    code = "submission_uncertain"


class KeyConflict(Error):
    """The API reports an existing resource and its id is known."""

    code = "key_conflict"
    _recovery = _CONFLICT_RECOVERY


class WaitTimeout(Error):
    """Local waiting stopped. The cloud job was not cancelled.

    No cancellation was requested. The job may still be running.
    """

    code = "wait_timeout"
    _recovery = _WAIT_RECOVERY


def exposed_request_id(exc: object) -> str | None:
    """Return a request id already present on ``exc``, if there is one."""
    status = getattr(exc, "status", None)
    for owner in (status, exc):
        if owner is None:
            continue
        found = _clean_request_id(getattr(owner, "request_id", None))
        if found is not None:
            return found
    return None


def _clean_request_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text == "":
        return None
    return text
