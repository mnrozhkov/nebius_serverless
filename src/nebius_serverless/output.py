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
from datetime import datetime, timezone
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
        self._stop_spinner()
        self._write(self._visible(_seen_parts(fact, self._stream)))
        if self.is_plain() or elapsed < SPINNER_AFTER:
            return
        self._show_spinner(self._visible(_progress_parts(
            fact.job_id,
            fact.state,
            elapsed,
            self._stream,
        )))

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


def show_record(
    record: dict[str, object] | None,
    *,
    job_id: str,
    name: str,
    stream: object,
) -> None:
    """Print one job record. ``stream`` is stdout for ``Run.display``."""
    color = (
        presentation_mode(stream) == "interactive" and not _no_color()
    )
    from rich.console import Console

    console = Console(
        file=stream,
        force_terminal=color,
        force_jupyter=False,
        force_interactive=color,
        no_color=True if not color else None,
        color_system=None if not color else "standard",
        markup=False,
        highlight=False,
        emoji=False,
        soft_wrap=True,
        width=4096,
        height=24,
    )
    for parts in _record_lines(record, job_id=job_id, name=name):
        if not parts:
            console.print("")
            continue
        console.print(
            _paint(parts, color=color),
            markup=False,
            highlight=False,
            soft_wrap=True,
            overflow="ignore",
            crop=False,
        )


def _record_lines(
    record: dict[str, object] | None,
    *,
    job_id: str,
    name: str,
) -> list[list[tuple[str, str]]]:
    shown_id, shown_name = _identity(record, job_id, name)
    lines: list[list[tuple[str, str]]] = [
        _header(shown_id, shown_name)
    ]
    if record is None:
        lines.append([("  no record yet", "dim")])
        return lines
    state = _record_state(record)
    if state is not None:
        lines.append([("  ", ""), (state, _state_style(state))])
    for block in (
        _spec_lines(record),
        _time_lines(record),
        _instance_lines(record),
    ):
        if not block:
            continue
        lines.append([])
        lines.extend(block)
    return lines


def _header(job_id: str, name: str) -> list[tuple[str, str]]:
    parts = [(plain_text(job_id), "bold cyan")]
    if name and name != job_id:
        parts.append(("  ", ""))
        parts.append((plain_text(name), ""))
    return parts


def _identity(
    record: dict[str, object] | None,
    job_id: str,
    name: str,
) -> tuple[str, str]:
    metadata = _mapping(None if record is None else record.get("metadata"))
    shown_id = _text(None if metadata is None else metadata.get("id"))
    shown_name = _text(None if metadata is None else metadata.get("name"))
    if shown_id == "":
        shown_id = job_id
    if shown_name == "":
        shown_name = name
    return shown_id, shown_name


def _spec_lines(
    record: dict[str, object],
) -> list[list[tuple[str, str]]]:
    spec = _mapping(record.get("spec"))
    if spec is None:
        return []
    rows: list[tuple[str, str]] = []
    _add(rows, "image", _text(spec.get("image")))
    _add(rows, "command", _command(spec))
    _add(rows, "platform", _text(spec.get("platform")))
    _add(rows, "preset", _text(spec.get("preset")))
    _add(rows, "disk", _disk(spec.get("disk")))
    _add(rows, "shm", _bytes(spec.get("shm_size_bytes")))
    timeout = _seconds(spec.get("timeout"))
    if timeout is not None:
        _add(rows, "timeout", _duration(timeout))
    _add(rows, "subnet", _text(spec.get("subnet_id")))
    return [_field(key, value) for key, value in rows]


def _time_lines(
    record: dict[str, object],
) -> list[list[tuple[str, str]]]:
    metadata = _mapping(record.get("metadata")) or {}
    status = _mapping(record.get("status")) or {}
    created = _moment(metadata.get("created_at"))
    started = _moment(status.get("started_at"))
    finished = _moment(status.get("finished_at"))
    rows: list[tuple[str, str]] = []
    if created is not None:
        _add(rows, "created", _stamp(created))
    if started is not None:
        _add(rows, "started", _stamp(started))
    if finished is not None:
        _add(rows, "finished", _stamp(finished))
    if created is not None and started is not None:
        _add(rows, "queued", _duration((started - created).total_seconds()))
    if started is not None and finished is not None:
        _add(rows, "ran", _duration((finished - started).total_seconds()))
    return [_field(key, value) for key, value in rows]


def _instance_lines(
    record: dict[str, object],
) -> list[list[tuple[str, str]]]:
    status = _mapping(record.get("status"))
    if status is None:
        return []
    items = status.get("instances")
    if not isinstance(items, list):
        return []
    lines: list[list[tuple[str, str]]] = []
    for item in items:
        mapped = _mapping(item)
        if mapped is None:
            continue
        parts: list[tuple[str, str]] = [("  ", ""), ("instance  ", "dim")]
        values: list[tuple[str, str]] = []
        _gap(values, _text(mapped.get("compute_instance_id")), "")
        _gap(values, _text(mapped.get("private_ip")), "")
        _gap(values, _text(mapped.get("state")), _state_style(
            _text(mapped.get("state"))
        ))
        if not values:
            continue
        parts.extend(values)
        lines.append(parts)
    return lines


def _add(rows: list[tuple[str, str]], key: str, value: str) -> None:
    if value != "":
        rows.append((key, value))


def _gap(
    parts: list[tuple[str, str]],
    value: str,
    style: str,
) -> None:
    if value == "":
        return
    if parts:
        parts.append(("  ", ""))
    parts.append((value, style))


def _field(key: str, value: str) -> list[tuple[str, str]]:
    return [
        ("  ", ""),
        (f"{key:<8}  ", "dim"),
        (plain_text(value), ""),
    ]


def _command(spec: dict[str, object]) -> str:
    raw = spec.get("container_command", spec.get("command"))
    if isinstance(raw, str):
        return plain_text(raw)
    if isinstance(raw, list):
        words = [plain_text(item) for item in raw if isinstance(item, str)]
        return " ".join(word for word in words if word)
    return ""


def _disk(value: object) -> str:
    mapped = _mapping(value)
    if mapped is None:
        return _text(value)
    parts = [
        _bytes(mapped.get("size_bytes")),
        _text(mapped.get("type")),
    ]
    return " ".join(part for part in parts if part)


def _bytes(value: object) -> str:
    number = _whole(value)
    if number is None:
        return ""
    gib = 1024**3
    if number % gib == 0:
        return f"{number // gib} GiB"
    if number >= gib:
        return f"{number / gib:.1f} GiB"
    mib = 1024**2
    if number % mib == 0:
        return f"{number // mib} MiB"
    return f"{number} B"


def _seconds(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    text = value.strip()
    scale = 1.0
    if text.endswith("ms"):
        return None
    if text.endswith("s"):
        text = text[:-1]
    elif text.endswith("m"):
        scale = 60.0
        text = text[:-1]
    elif text.endswith("h"):
        scale = 3600.0
        text = text[:-1]
    try:
        return float(text) * scale
    except ValueError:
        return None


def _duration(seconds: float) -> str:
    whole = int(round(seconds))
    if whole < 0:
        whole = 0
    hours, rem = divmod(whole, 3600)
    minutes, secs = divmod(rem, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if secs or not parts:
        parts.append(f"{secs}s")
    return " ".join(parts)


def _moment(value: object) -> datetime | None:
    if not isinstance(value, str) or value.strip() == "":
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    if "." in text:
        head, tail = text.split(".", 1)
        digits: list[str] = []
        suffix = ""
        for index, char in enumerate(tail):
            if char.isdigit() and len(digits) < 6:
                digits.append(char)
                continue
            suffix = tail[index:]
            break
        text = f"{head}.{''.join(digits)}{suffix}" if digits else (
            f"{head}{suffix}"
        )
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M:%SZ")


def _record_state(record: dict[str, object]) -> str | None:
    status = _mapping(record.get("status"))
    if status is None:
        return None
    state = status.get("state")
    if not isinstance(state, str) or state == "":
        return None
    return plain_text(state)


def _mapping(value: object) -> dict[str, object] | None:
    if isinstance(value, dict):
        return value
    return None


def _text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return plain_text(value)


def _whole(value: object) -> int | None:
    if isinstance(value, bool) or isinstance(value, float):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


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


def _seen_parts(
    fact: Status,
    stream: object,
) -> list[tuple[str, str]]:
    """One lifecycle line: the state and when it was first seen."""
    return [
        (plain_text(fact.job_id), "bold cyan"),
        (" ", ""),
        (_label(fact.state), _state_style(fact.state)),
        *_at(stream, fact.observed_seconds),
    ]


def _cancel_parts(job_id: str) -> list[tuple[str, str]]:
    return [
        ("Cancel accepted for ", "dim"),
        (plain_text(job_id), "bold cyan"),
    ]


def _at(
    stream: object,
    seconds: float | None,
) -> list[tuple[str, str]]:
    """Seconds since the wait started, when this state was first seen."""
    return [
        (_dot(stream), "dim"),
        (format_seconds(seconds or 0), ""),
    ]


def _terminal_parts(
    fact: Status,
    stream: object,
) -> list[tuple[str, str]]:
    job_id = plain_text(fact.job_id)
    state = plain_text(fact.state or "")
    when = _at(stream, fact.observed_seconds)
    if state in _FAILED:
        mark = _bad_mark(stream)
        return [
            (f"{mark} ", "bold red"),
            (job_id, "bold cyan"),
            (" ", ""),
            (state, "bold red"),
            *when,
            ("\n  ", ""),
            (_FAILURE_RECOVERY, "dim"),
        ]
    if state == "COMPLETED":
        mark = _ok_mark(stream)
        return [
            (f"{mark} ", "bold green"),
            (job_id, "bold cyan"),
            (" ", ""),
            ("COMPLETED", "bold green"),
            *when,
        ]
    return [
        (job_id, "bold cyan"),
        (" ", ""),
        (_label(fact.state), _state_style(fact.state)),
        *when,
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
