"""Per-call progress and the one live display.

Rich is constructed only when a call renders. ``quiet=True`` does not
build a console and does not take a display slot.
"""

import logging
import os
import sys
import threading
import time
import uuid
from collections.abc import Callable
from typing import TypeVar

from .errors import Error
from .log import emit, plain_text, presentation_mode
from .status import Status

SPINNER_AFTER = 0.3
_LOG_FACT = {
    "submitted": (
        logging.INFO,
        "Submission acknowledged",
        "submission",
    ),
    "snapshot": (logging.DEBUG, "Fetched job", "snapshot"),
    "transition": (
        logging.INFO,
        "Observed a state change",
        "state_change",
    ),
    "terminal": (
        logging.INFO,
        "Job reached a terminal state",
        "terminal",
    ),
    "cancel_accepted": (
        logging.INFO,
        "Cancel accepted",
        "cancel_accepted",
    ),
    "local_timeout": (
        logging.INFO,
        "Local waiting ended",
        "local_timeout",
    ),
}
_FAILED = frozenset({"FAILED", "ERROR"})
_FAILURE_RECOVERY = (
    "Reload it with jobs.get(id). Do not send a second create."
)

T = TypeVar("T")


class Progress:
    """Progress for one public call. Closing it does not cancel a job."""

    def __init__(self, *, quiet: bool, logger_name: str) -> None:
        self.quiet = quiet
        self.logger_name = logger_name
        self.operation_id = uuid.uuid4().hex
        self.closed = False
        self._stream = sys.stderr
        self._console: object | None = None
        self._console_interactive = False
        self._status: object | None = None
        self._demoted = False
        self._registered = False

    def begin_wait(self) -> None:
        """Take the live-display slot unless this call is quiet."""
        if self.quiet or self.closed:
            return
        _coordinator.acquire(self)

    def close(self) -> None:
        """Stop rendering. Later renders no-op and do not restart."""
        with _coordinator.lock:
            if self.closed:
                return
            self.closed = True
            self._stop_spinner()
            _coordinator.release(self)

    def demote(self) -> None:
        """Leave the spinner and use append-only lines. Lock is held."""
        self._demoted = True
        self._stop_spinner()
        self._console = None
        self._console_interactive = False

    def render(self, fact: Status) -> None:
        """Draw ``fact`` when this call is visible and still open."""
        if self.quiet or self.closed:
            return
        with _coordinator.lock:
            if self.quiet or self.closed:
                return
            if self.is_plain():
                self._stop_spinner()
            self._render(fact)

    def refresh_spinner(
        self,
        *,
        job_id: str,
        state: str | None,
        elapsed: float,
    ) -> None:
        """Update the in-progress line without adding a permanent one."""
        if self.quiet or self.closed:
            return
        with _coordinator.lock:
            if self.quiet or self.closed:
                return
            if self.is_plain() or elapsed < SPINNER_AFTER:
                return
            self._show_spinner(self._visible(_progress_parts(
                job_id,
                state,
                elapsed,
                self._stream,
            )))

    def is_plain(self) -> bool:
        """True when this call must not move the cursor."""
        if self._demoted:
            return True
        logger = logging.getLogger("nebius_serverless")
        if logger.isEnabledFor(logging.DEBUG):
            return True
        return presentation_mode(self._stream) == "plain"

    def _color(self) -> bool:
        """True when this call may use color as well as words."""
        return (not self.is_plain()) and (not _no_color())

    def _visible(self, parts: list[tuple[str, str]]) -> object:
        """Join ``parts``. Color them only when this call allows it."""
        return _paint(parts, color=self._color())

    def _render(self, fact: Status) -> None:
        if fact.kind == "submitted":
            self._write(self._visible(_submitted_parts(fact, self._stream)))
            return
        if fact.kind == "snapshot":
            self._write(self._visible(_snapshot_parts(fact)))
            return
        if fact.kind == "cancel_accepted":
            self._write(self._visible(_cancel_parts(fact.job_id)))
            return
        if fact.kind == "local_timeout":
            self._stop_spinner()
            self._write(fact.message or "")
            return
        if fact.kind == "terminal":
            self._stop_spinner()
            self._write(self._visible(_terminal_parts(fact, self._stream)))
            return
        if fact.kind == "transition":
            self._render_transition(fact)

    def _render_transition(self, fact: Status) -> None:
        elapsed = fact.observed_seconds or 0.0
        line = _progress_parts(
            fact.job_id,
            fact.state,
            elapsed,
            self._stream,
        )
        if fact.previous is None:
            if self.is_plain():
                self._write(self._visible(line))
                return
            if elapsed >= SPINNER_AFTER:
                self._show_spinner(self._visible(line))
            return
        self._write(self._visible(_change_parts(fact)))
        if self.is_plain() or elapsed < SPINNER_AFTER:
            return
        self._show_spinner(self._visible(line))

    def _write(self, text: object) -> None:
        if isinstance(text, str):
            if text == "":
                return
            console = self._console_for(interactive=not self.is_plain())
            for line in text.split("\n"):
                console.print(
                    line,
                    markup=False,
                    highlight=False,
                    soft_wrap=True,
                    overflow="ignore",
                    crop=False,
                )
            return
        plain = getattr(text, "plain", None)
        if not isinstance(plain, str) or plain == "":
            return
        console = self._console_for(interactive=not self.is_plain())
        console.print(
            text,
            markup=False,
            highlight=False,
            soft_wrap=True,
            overflow="ignore",
            crop=False,
        )

    def _show_spinner(self, text: object) -> None:
        if self.closed or self.is_plain():
            return
        status = self._status
        if status is None:
            from rich.status import Status as RichStatus

            console = self._console_for(interactive=True)
            name = "dots" if _can_encode(self._stream, "⠋") else "line"
            style = "bold cyan" if self._color() else "status.spinner"
            status = RichStatus(
                text,
                console=console,
                spinner=name,
                spinner_style=style,
                refresh_per_second=4,
            )
            # Status redirects the process streams unless this is off.
            status._live._redirect_stdout = False
            status._live._redirect_stderr = False
            self._status = status
            status.start()
            status._live.refresh()
            return
        status.update(text)

    def _stop_spinner(self) -> None:
        status = self._status
        self._status = None
        if status is None:
            return
        live = getattr(status, "_live", None)
        thread = getattr(live, "_refresh_thread", None)
        status.stop()
        if thread is not None and thread.is_alive():
            thread.join(timeout=1)

    def _console_for(self, *, interactive: bool) -> object:
        if (
            self._console is not None
            and self._console_interactive == interactive
        ):
            return self._console
        from rich.console import Console

        no_color = (not interactive) or _no_color()
        self._console_interactive = interactive
        self._console = Console(
            file=self._stream,
            force_terminal=interactive,
            force_jupyter=False,
            force_interactive=interactive,
            no_color=True if no_color else None,
            color_system=None if no_color else "auto",
            markup=False,
            highlight=False,
            emoji=False,
            soft_wrap=True,
            width=4096,
            height=24,
        )
        return self._console


class _Coordinator:
    """The one live spinner. Not a session and not an event bus."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self._waits: dict[int, Progress] = {}

    def acquire(self, handle: Progress) -> None:
        with self.lock:
            self._drop_closed()
            if handle.quiet or handle.closed or handle._registered:
                return
            self._waits[id(handle)] = handle
            handle._registered = True
            if len(self._waits) < 2:
                return
            for item in self._waits.values():
                item.demote()

    def release(self, handle: Progress) -> None:
        self._waits.pop(id(handle), None)
        handle._registered = False

    def _drop_closed(self) -> None:
        closed = [
            key for key, item in self._waits.items() if item.closed
        ]
        for key in closed:
            self._waits.pop(key, None)


_coordinator = _Coordinator()


class Follow:
    """How one ``wait`` renders polls. The handle is shared."""

    def __init__(self, handle: Progress, job_id: str) -> None:
        self._handle = handle
        self._job_id = job_id
        self._previous: str | None = None

    def poll(
        self,
        *,
        state: str | None,
        elapsed: float,
        attempt: int,
        duration_ms: int,
        terminal: bool,
    ) -> None:
        """Log this poll, then render when the handle is still open."""
        emit(
            self._handle.logger_name,
            logging.DEBUG,
            "Polled job",
            event="poll",
            operation_id=self._handle.operation_id,
            job_id=self._job_id,
            attempt=attempt,
            duration_ms=duration_ms,
        )
        if terminal:
            report(
                Status(
                    kind="terminal",
                    job_id=self._job_id,
                    state=state,
                    previous=self._previous,
                    observed_seconds=elapsed,
                ),
                self._handle,
            )
            self._previous = state
            return
        if self._previous is None or state != self._previous:
            report(
                Status(
                    kind="transition",
                    job_id=self._job_id,
                    state=state,
                    previous=self._previous,
                    observed_seconds=elapsed,
                ),
                self._handle,
            )
            self._previous = state
            return
        self._handle.refresh_spinner(
            job_id=self._job_id,
            state=state,
            elapsed=elapsed,
        )

    def timed_out(self, seconds: float) -> None:
        """Log that local waiting ended and print the guidance."""
        report(
            Status(
                kind="local_timeout",
                job_id=self._job_id,
                observed_seconds=seconds,
                message=timeout_text(self._job_id, seconds),
            ),
            self._handle,
        )


def call_progress(
    *,
    quiet: bool,
    logger_name: str,
    work: Callable[[Progress], T],
) -> T:
    """Run ``work`` with a handle, then close that handle."""
    progress = Progress(quiet=quiet, logger_name=logger_name)
    try:
        return work(progress)
    except Error as exc:
        if exc.code != "wait_timeout":
            show_failure(progress, exc)
        raise
    finally:
        progress.close()


async def call_progress_async(
    *,
    quiet: bool,
    logger_name: str,
    work: Callable[[Progress], T],
) -> T:
    """Share ``work``'s handle with the worker and close it here.

    Closing the handle does not cancel the cloud job. If the await is
    cancelled while the worker is still polling, later renders no-op.
    """
    import asyncio

    progress = Progress(quiet=quiet, logger_name=logger_name)
    try:
        return await asyncio.to_thread(work, progress)
    except Error as exc:
        if exc.code != "wait_timeout":
            show_failure(progress, exc)
        raise
    finally:
        progress.close()


def report(fact: Status, handle: Progress) -> None:
    """Log one fact, then render it when the handle is open."""
    level, message, event = _LOG_FACT[fact.kind]
    if fact.kind == "transition" and fact.previous is None:
        message = "Observed job state"
        event = "state_observed"
    emit(
        handle.logger_name,
        level,
        message,
        event=event,
        operation_id=handle.operation_id,
        request_id=fact.request_id,
        job_id=fact.job_id or None,
        attempt=fact.attempt,
        duration_ms=fact.duration_ms,
    )
    handle.render(fact)


def log_transport(
    handle: Progress,
    *,
    job_id: str | None,
    attempt: int,
    duration_ms: int,
    request_id: str | None = None,
    status_code: int | None = None,
) -> None:
    """Log one create, get, or cancel attempt. Does not render."""
    emit(
        handle.logger_name,
        logging.DEBUG,
        "Transport attempt",
        event="transport",
        operation_id=handle.operation_id,
        request_id=request_id,
        job_id=job_id,
        attempt=attempt,
        duration_ms=duration_ms,
        status_code=status_code,
    )


def show_failure(handle: Progress, exc: Error) -> None:
    """Print the safe message and recovery. The exception still raises."""
    if handle.quiet or handle.closed:
        return
    message = plain_text(str(exc)) or "The call failed."
    recovery = plain_text(exc.recovery)
    mark = _bad_mark(handle._stream)
    parts = [(f"{mark} {message}", "bold red")]
    if recovery and recovery not in message:
        parts.append(("\n  ", ""))
        parts.append((recovery, "dim"))
    with _coordinator.lock:
        if handle.quiet or handle.closed:
            return
        handle._write(handle._visible(parts))


def elapsed_ms(started: float) -> int:
    """Whole milliseconds since ``started`` on the performance clock."""
    return max(0, int((time.perf_counter() - started) * 1000))


def format_seconds(value: float) -> str:
    """Render a duration as ``12s`` or ``1.5s``."""
    if value < 0:
        value = 0.0
    rounded = round(float(value), 1)
    if rounded == int(rounded):
        return f"{int(rounded)}s"
    return f"{rounded:.1f}s"


def timeout_text(job_id: str, seconds: float) -> str:
    """The three lines for a local wait that did not cancel the job."""
    shown = format_seconds(seconds)
    identity = plain_text(job_id)
    return (
        f"Stopped waiting for {identity} after {shown}.\n"
        "The job may still be running remotely.\n"
        "Reload it with jobs.get(id), "
        "or explicitly request cancellation."
    )


def _paint(parts: list[tuple[str, str]], *, color: bool) -> object:
    """Join segments. Apply styles only when ``color`` is on."""
    if not color:
        return "".join(text for text, _style in parts)
    from rich.text import Text

    line = Text()
    for text, style in parts:
        if text:
            line.append(text, style=style or None)
    return line


def _state_style(state: str | None) -> str:
    """Color for a state word. The word itself stays in the line."""
    label = _label(state)
    if label == "COMPLETED":
        return "bold green"
    if label in _FAILED:
        return "bold red"
    return "yellow"


def _submitted_parts(
    fact: Status,
    stream: object,
) -> list[tuple[str, str]]:
    job_id = plain_text(fact.job_id)
    name = plain_text(fact.name)
    parts = [
        ("Submitted job ", "dim"),
        (job_id, "bold cyan"),
    ]
    if name:
        parts.append((" ", ""))
        parts.append((name, ""))
    if fact.state:
        parts.append((_dot(stream), "dim"))
        parts.append((plain_text(fact.state), _state_style(fact.state)))
    return parts


def _snapshot_parts(fact: Status) -> list[tuple[str, str]]:
    return [
        (plain_text(fact.job_id), "bold cyan"),
        (" ", ""),
        (_label(fact.state), _state_style(fact.state)),
    ]


def _progress_parts(
    job_id: str,
    state: str | None,
    elapsed: float,
    stream: object,
) -> list[tuple[str, str]]:
    shown = format_seconds(elapsed)
    return [
        (plain_text(job_id), "bold cyan"),
        (" ", ""),
        (_label(state), _state_style(state)),
        (_dot(stream), "dim"),
        ("observed for ", "dim"),
        (shown, ""),
    ]


def _change_parts(fact: Status) -> list[tuple[str, str]]:
    return [
        (plain_text(fact.job_id), "bold cyan"),
        (" ", ""),
        (_label(fact.previous), "dim"),
        (" -> ", "dim"),
        (_label(fact.state), _state_style(fact.state)),
    ]


def _cancel_parts(job_id: str) -> list[tuple[str, str]]:
    return [
        ("Cancel accepted for ", "dim"),
        (plain_text(job_id), "bold cyan"),
    ]


def _terminal_parts(
    fact: Status,
    stream: object,
) -> list[tuple[str, str]]:
    job_id = plain_text(fact.job_id)
    state = plain_text(fact.state or "")
    if state in _FAILED:
        mark = _bad_mark(stream)
        return [
            (f"{mark} ", "bold red"),
            (job_id, "bold cyan"),
            (" ", ""),
            (state, "bold red"),
            ("\n  ", ""),
            (_FAILURE_RECOVERY, "dim"),
        ]
    shown = format_seconds(fact.observed_seconds or 0)
    if state == "COMPLETED":
        mark = _ok_mark(stream)
        return [
            (f"{mark} ", "bold green"),
            (job_id, "bold cyan"),
            (" ", ""),
            ("COMPLETED", "bold green"),
            (_dot(stream), "dim"),
            ("observed for ", "dim"),
            (shown, ""),
        ]
    return [
        (job_id, "bold cyan"),
        (" ", ""),
        (_label(fact.state), _state_style(fact.state)),
        (_dot(stream), "dim"),
        ("observed for ", "dim"),
        (shown, ""),
    ]


def _label(state: str | None) -> str:
    text = plain_text(state or "")
    if text == "":
        return "Waiting for execution"
    return text


def _dot(stream: object) -> str:
    if _can_encode(stream, "·"):
        return " · "
    return " - "


def _ok_mark(stream: object) -> str:
    if _can_encode(stream, "✓"):
        return "✓"
    return "ok"


def _bad_mark(stream: object) -> str:
    if _can_encode(stream, "✗"):
        return "✗"
    return "x"


def _can_encode(stream: object, text: str) -> bool:
    encoding = getattr(stream, "encoding", None)
    if not isinstance(encoding, str) or encoding == "":
        return True
    try:
        text.encode(encoding)
    except (LookupError, UnicodeError):
        return False
    return True


def _no_color() -> bool:
    return os.environ.get("NO_COLOR", "") != ""
