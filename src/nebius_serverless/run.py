"""One cloud job, and the collection addressed by id."""

import time

from .errors import ValidationError, WaitTimeout
from .loop import reject_running_loop
from .transport import Transport

TERMINAL_STATES = frozenset(
    {"COMPLETED", "FAILED", "CANCELLED", "ERROR"}
)
POLL_SECONDS = 1.0


def monotonic() -> float:
    """Seconds used to decide when a local wait is over."""
    return time.monotonic()


def sleep(seconds: float) -> None:
    """Pause between polls. Tests replace this with a fake clock."""
    time.sleep(seconds)


def state_of(record: dict[str, object] | None) -> str | None:
    """Return the raw ``status.state`` string, when the record has one."""
    if record is None:
        return None
    status = record.get("status")
    if not isinstance(status, dict):
        return None
    state = status.get("state")
    if not isinstance(state, str) or state == "":
        return None
    return state


class Run:
    """One Nebius job id.

    ``get``, ``wait``, and ``cancel`` need that id. Property reads do
    not perform I/O. ``wait`` polls until the state is terminal or the
    local timeout expires. It does not cancel the cloud job.
    """

    def __init__(
        self,
        job_id: str,
        *,
        name: str,
        transport: Transport,
        create_state: str | None = None,
        record: dict[str, object] | None = None,
    ) -> None:
        self._id = job_id
        self._name = name
        self._transport = transport
        self._create_state = create_state
        self._record = record

    @property
    def id(self) -> str:
        """Nebius job id. Reading it does not perform I/O."""
        return self._id

    @property
    def name(self) -> str:
        """Display name. Lookup does not use it."""
        return self._name

    @property
    def record(self) -> dict[str, object] | None:
        """Last fetched JSON, or None before the first successful fetch."""
        return self._record

    @property
    def status(self) -> str | None:
        """Raw state from the last fetch, else the create response."""
        if self._record is not None:
            return state_of(self._record)
        return self._create_state

    def get(self) -> dict[str, object]:
        """Fetch the job once and return its JSON."""
        reject_running_loop("get_async")
        return self._get()

    async def get_async(self) -> dict[str, object]:
        """Await the same fetch as ``get``."""
        import asyncio

        return await asyncio.to_thread(self._get)

    def wait(self, timeout: float | None = None) -> dict[str, object]:
        """Poll ``get`` until the state is terminal.

        ``timeout=0`` is one fetch. A local timeout leaves the cloud
        job running. Failed and cancelled states are returned as data.
        """
        reject_running_loop("wait_async")
        return self._wait(timeout)

    async def wait_async(
        self,
        timeout: float | None = None,
    ) -> dict[str, object]:
        """Await the same poll as ``wait``.

        Cancelling this await does not cancel the cloud job.
        """
        import asyncio

        return await asyncio.to_thread(self._wait, timeout)

    def cancel(self) -> dict[str, object]:
        """Request cancellation and return when it is accepted.

        The payload does not claim the container has stopped.
        """
        reject_running_loop("cancel_async")
        return self._cancel()

    async def cancel_async(self) -> dict[str, object]:
        """Await the same cancellation request as ``cancel``."""
        import asyncio

        return await asyncio.to_thread(self._cancel)

    def _get(self) -> dict[str, object]:
        record = self._transport.get(self._id)
        self._record = record
        return record

    def _cancel(self) -> dict[str, object]:
        return self._transport.cancel(self._id)

    def _wait(self, timeout: float | None) -> dict[str, object]:
        deadline = _deadline(timeout, self._id)
        one_fetch = timeout is not None and timeout <= 0
        while True:
            record = self._get()
            if state_of(record) in TERMINAL_STATES:
                return record
            if one_fetch or _expired(deadline):
                raise _timeout(self._id)
            pause = POLL_SECONDS
            if deadline is not None:
                pause = min(pause, deadline - monotonic())
            sleep(pause)
            if _expired(deadline):
                raise _timeout(self._id)


class Jobs:
    """Cloud jobs addressed by a saved id string."""

    def get(
        self,
        job_id: str,
        *,
        profile: str | None = None,
        project: str | None = None,
        transport: Transport | None = None,
    ) -> Run:
        """Fetch ``job_id`` once and return a ``Run``. Does not create."""
        reject_running_loop("get_async")
        return self._get(
            job_id,
            profile=profile,
            project=project,
            transport=transport,
        )

    async def get_async(
        self,
        job_id: str,
        *,
        profile: str | None = None,
        project: str | None = None,
        transport: Transport | None = None,
    ) -> Run:
        """Await the same fetch as ``get``."""
        import asyncio

        return await asyncio.to_thread(
            self._get,
            job_id,
            profile=profile,
            project=project,
            transport=transport,
        )

    def _get(
        self,
        job_id: str,
        *,
        profile: str | None,
        project: str | None,
        transport: Transport | None,
    ) -> Run:
        chosen = transport or _sdk_transport(profile, project)
        record = chosen.get(job_id)
        name = _record_name(record)
        return Run(
            job_id,
            name=name,
            transport=chosen,
            record=record,
        )


jobs = Jobs()


def _sdk_transport(
    profile: str | None,
    project: str | None,
) -> Transport:
    from .sdk_transport import SdkTransport

    return SdkTransport(profile=profile, project=project)


def _record_name(record: dict[str, object]) -> str:
    metadata = record.get("metadata")
    if not isinstance(metadata, dict):
        return ""
    name = metadata.get("name")
    if isinstance(name, str):
        return name
    return ""


def _deadline(timeout: float | None, job_id: str) -> float | None:
    if timeout is None:
        return None
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise ValidationError(
            "wait timeout must be a number of seconds or None.",
            operation="wait",
            run_id=job_id,
        )
    if timeout < 0:
        raise ValidationError(
            "wait timeout must be zero or greater.",
            operation="wait",
            run_id=job_id,
        )
    return monotonic() + float(timeout)


def _expired(deadline: float | None) -> bool:
    return deadline is not None and monotonic() >= deadline


def _timeout(job_id: str) -> WaitTimeout:
    return WaitTimeout(
        "The local wait ended. The cloud job is unchanged.",
        operation="wait",
        run_id=job_id,
    )
