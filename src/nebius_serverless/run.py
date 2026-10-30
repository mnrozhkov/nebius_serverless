"""One cloud job, and the collection addressed by id."""

import time

from .errors import Error, ValidationError, WaitTimeout
from .loop import reject_running_loop
from .output import (
    Follow,
    Progress,
    call_progress,
    call_progress_async,
    elapsed_ms,
    log_transport,
    report,
    timeout_text,
)
from .status import Status
from .transport import Transport

_LOG = "nebius_serverless.run"

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

    def get(self, *, quiet: bool = False) -> dict[str, object]:
        """Fetch the job once and return its JSON.

        Prints one snapshot. ``quiet=True`` suppresses it for this
        call only and is not stored on the run.
        """
        reject_running_loop("get_async")

        def work(progress: Progress) -> dict[str, object]:
            return self._present_get(progress)

        return call_progress(quiet=quiet, logger_name=_LOG, work=work)

    async def get_async(self, *, quiet: bool = False) -> dict[str, object]:
        """Await the same fetch as ``get``.

        ``quiet=True`` suppresses progress for this call only.
        """

        def work(progress: Progress) -> dict[str, object]:
            return self._present_get(progress)

        return await call_progress_async(
            quiet=quiet,
            logger_name=_LOG,
            work=work,
        )

    def wait(
        self,
        timeout: float | None = None,
        *,
        quiet: bool = False,
    ) -> dict[str, object]:
        """Poll ``get`` until the state is terminal.

        ``timeout=0`` is one fetch. A local timeout leaves the cloud
        job running. Failed and cancelled states are returned as data.
        Progress shows the observation and the outcome. ``quiet=True``
        suppresses it for this call only.
        """
        reject_running_loop("wait_async")

        def work(progress: Progress) -> dict[str, object]:
            return self._wait(timeout, progress)

        return call_progress(quiet=quiet, logger_name=_LOG, work=work)

    async def wait_async(
        self,
        timeout: float | None = None,
        *,
        quiet: bool = False,
    ) -> dict[str, object]:
        """Await the same poll as ``wait``.

        Cancelling this await does not cancel the cloud job. The
        progress handle is closed here, including when the await is
        cancelled, so a worker that is still polling prints nothing
        further.
        """

        def work(progress: Progress) -> dict[str, object]:
            return self._wait(timeout, progress)

        return await call_progress_async(
            quiet=quiet,
            logger_name=_LOG,
            work=work,
        )

    def cancel(self, *, quiet: bool = False) -> dict[str, object]:
        """Request cancellation and return when it is accepted.

        The payload does not claim the container has stopped.
        ``quiet=True`` suppresses the acceptance line for this call.
        """
        reject_running_loop("cancel_async")

        def work(progress: Progress) -> dict[str, object]:
            return self._present_cancel(progress)

        return call_progress(quiet=quiet, logger_name=_LOG, work=work)

    async def cancel_async(
        self,
        *,
        quiet: bool = False,
    ) -> dict[str, object]:
        """Await the same cancellation request as ``cancel``."""

        def work(progress: Progress) -> dict[str, object]:
            return self._present_cancel(progress)

        return await call_progress_async(
            quiet=quiet,
            logger_name=_LOG,
            work=work,
        )

    def _get(self) -> dict[str, object]:
        record = self._transport.get(self._id)
        self._record = record
        return record

    def _present_get(self, progress: Progress) -> dict[str, object]:
        started = time.perf_counter()
        try:
            record = self._get()
        except Error as exc:
            log_transport(
                progress,
                job_id=self._id,
                attempt=1,
                duration_ms=elapsed_ms(started),
                request_id=exc.request_id,
            )
            raise
        report(
            Status(
                kind="snapshot",
                job_id=self._id,
                state=state_of(record),
                attempt=1,
                duration_ms=elapsed_ms(started),
            ),
            progress,
        )
        return record

    def _cancel(self) -> dict[str, object]:
        return self._transport.cancel(self._id)

    def _present_cancel(self, progress: Progress) -> dict[str, object]:
        started = time.perf_counter()
        try:
            payload = self._cancel()
        except Error as exc:
            log_transport(
                progress,
                job_id=self._id,
                attempt=1,
                duration_ms=elapsed_ms(started),
                request_id=exc.request_id,
            )
            raise
        duration_ms = elapsed_ms(started)
        log_transport(
            progress,
            job_id=self._id,
            attempt=1,
            duration_ms=duration_ms,
        )
        report(
            Status(
                kind="cancel_accepted",
                job_id=self._id,
                duration_ms=duration_ms,
            ),
            progress,
        )
        return payload

    def _wait(
        self,
        timeout: float | None,
        progress: Progress,
    ) -> dict[str, object]:
        deadline = _deadline(timeout, self._id)
        one_fetch = timeout is not None and timeout <= 0
        progress.begin_wait()
        started = monotonic()
        follow = Follow(progress, self._id)
        attempt = 0
        while True:
            attempt += 1
            began = time.perf_counter()
            try:
                record = self._get()
            except Error as exc:
                log_transport(
                    progress,
                    job_id=self._id,
                    attempt=attempt,
                    duration_ms=elapsed_ms(began),
                    request_id=exc.request_id,
                )
                raise
            elapsed = monotonic() - started
            follow.poll(
                state=state_of(record),
                elapsed=elapsed,
                attempt=attempt,
                duration_ms=elapsed_ms(began),
                terminal=state_of(record) in TERMINAL_STATES,
            )
            if state_of(record) in TERMINAL_STATES:
                return record
            if one_fetch or _expired(deadline):
                _give_up(follow, timeout, self._id)
            pause = POLL_SECONDS
            if deadline is not None:
                pause = min(pause, deadline - monotonic())
            sleep(pause)
            if _expired(deadline):
                _give_up(follow, timeout, self._id)


class Jobs:
    """Cloud jobs addressed by a saved id string."""

    def get(
        self,
        job_id: str,
        *,
        profile: str | None = None,
        project: str | None = None,
        transport: Transport | None = None,
        quiet: bool = False,
    ) -> Run:
        """Fetch ``job_id`` once and return a ``Run``. Does not create.

        Prints one snapshot. ``quiet=True`` suppresses it for this call.
        """
        reject_running_loop("get_async")

        def work(progress: Progress) -> Run:
            return self._get(
                job_id,
                profile=profile,
                project=project,
                transport=transport,
                progress=progress,
            )

        return call_progress(quiet=quiet, logger_name=_LOG, work=work)

    async def get_async(
        self,
        job_id: str,
        *,
        profile: str | None = None,
        project: str | None = None,
        transport: Transport | None = None,
        quiet: bool = False,
    ) -> Run:
        """Await the same fetch as ``get``.

        ``quiet=True`` suppresses progress for this call only.
        """

        def work(progress: Progress) -> Run:
            return self._get(
                job_id,
                profile=profile,
                project=project,
                transport=transport,
                progress=progress,
            )

        return await call_progress_async(
            quiet=quiet,
            logger_name=_LOG,
            work=work,
        )

    def _get(
        self,
        job_id: str,
        *,
        profile: str | None,
        project: str | None,
        transport: Transport | None,
        progress: Progress,
    ) -> Run:
        chosen = transport or _sdk_transport(profile, project)
        started = time.perf_counter()
        try:
            record = chosen.get(job_id)
        except Error as exc:
            log_transport(
                progress,
                job_id=job_id,
                attempt=1,
                duration_ms=elapsed_ms(started),
                request_id=exc.request_id,
            )
            raise
        report(
            Status(
                kind="snapshot",
                job_id=job_id,
                state=state_of(record),
                attempt=1,
                duration_ms=elapsed_ms(started),
            ),
            progress,
        )
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


def _give_up(follow: Follow, timeout: float | None, job_id: str) -> None:
    seconds = 0.0 if timeout is None else float(timeout)
    follow.timed_out(seconds)
    raise _timeout(job_id, seconds)


def _timeout(job_id: str, seconds: float) -> WaitTimeout:
    return WaitTimeout(
        timeout_text(job_id, seconds),
        operation="wait",
        run_id=job_id,
    )
