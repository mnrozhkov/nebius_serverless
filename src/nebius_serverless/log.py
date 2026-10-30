"""Diagnostics for ``nebius_serverless``.

Importing this module attaches a ``NullHandler`` and nothing else. It
does not configure an application handler, open a console, or touch
the network.
"""

import logging
import os
import platform
import sys

from .errors import ValidationError

_PACKAGE = "nebius_serverless"
_EXTRAS = (
    "event",
    "operation_id",
    "request_id",
    "job_id",
    "attempt",
    "duration_ms",
    "status_code",
)
_CI = ("CI", "GITHUB_ACTIONS", "GITLAB_CI")


class _Formatter(logging.Formatter):
    """Message text, plus allowlisted extras when DEBUG is configured."""

    def __init__(self, *, debug: bool) -> None:
        super().__init__("%(message)s")
        self._debug = debug

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        if not self._debug:
            return message
        parts: list[str] = []
        for key in _EXTRAS:
            value = getattr(record, key, None)
            if value is None or value == "":
                continue
            parts.append(f"{key}={plain_text(str(value))}")
        if not parts:
            return message
        return f"{message} {' '.join(parts)}"


class _SdkHandler(logging.StreamHandler):
    """Stderr handler owned by :func:`configure_logging`."""

    def __init__(self, level: int) -> None:
        super().__init__(sys.stderr)
        self.apply(level)

    def apply(self, level: int) -> None:
        """Point the formatter at ``level`` without adding a handler."""
        self.setFormatter(_Formatter(debug=level <= logging.DEBUG))


def _package_logger() -> logging.Logger:
    return logging.getLogger(_PACKAGE)


def _install_null_handler() -> None:
    logger = _package_logger()
    for handler in logger.handlers:
        if isinstance(handler, logging.NullHandler):
            return
    logger.addHandler(logging.NullHandler())


_install_null_handler()


def plain_text(value: str) -> str:
    """Drop terminal controls so a field stays on one line."""
    text = _without_csi(value)
    return "".join(char for char in text if _visible(char))


def emit(
    logger_name: str,
    level: int,
    message: str,
    **fields: object,
) -> None:
    """Log ``message`` with allowlisted extras that are present.

    The message is a fixed sentence. Job records and raw exceptions are
    not interpolated into it.
    """
    extra: dict[str, object] = {}
    for key in _EXTRAS:
        if key not in fields:
            continue
        value = _extra_value(fields[key])
        if value is None:
            continue
        extra[key] = value
    logging.getLogger(logger_name).log(level, "%s", message, extra=extra)


def configure_logging(*, level: str | int = "INFO") -> None:
    """Send diagnostics to stderr when the application has not.

    Applications that already configure logging should set the
    ``nebius_serverless`` logger themselves. This helper is for a
    script that has not.

    Each call sets the package logger level to ``level``. An existing
    handler owned by this helper is updated in place. Application
    handlers, their levels, and their filters are left alone. A
    ``NullHandler`` is not treated as a configured handler. When an
    application handler is already reachable on this logger or an
    ancestor, no handler is added and propagation is left as it is.
    Otherwise one stderr handler is added and propagation is turned
    off so the root logger does not print the same record.
    """
    numeric = _level(level)
    logger = _package_logger()
    logger.setLevel(numeric)
    owned = _owned_handler(logger)
    if owned is not None:
        owned.apply(numeric)
    if _application_handler_reachable(logger):
        return
    if owned is not None:
        return
    logger.addHandler(_SdkHandler(numeric))
    logger.propagate = False


def diagnostics() -> dict[str, str]:
    """Return local metadata. This prints nothing and contacts nobody.

    The dict has the package version, the Python version, the OS
    platform, and ``presentation``: ``plain`` or ``interactive`` for
    the current stderr. It does not report an ambient quiet setting.
    A call such as ``run.wait(quiet=True)`` suppresses progress for
    that call only. No profile, environment values, credentials, or
    job records are included.
    """
    module = sys.modules.get("nebius_serverless")
    version = getattr(module, "__version__", "0.0.1")
    if not isinstance(version, str):
        version = "0.0.1"
    return {
        "version": version,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "presentation": presentation_mode(sys.stderr),
    }


def presentation_mode(stream: object | None = None) -> str:
    """Return ``plain`` or ``interactive`` for ``stream``.

    A non-tty, a dumb terminal, a Jupyter or IPython kernel, and the
    ``CI``, ``GITHUB_ACTIONS``, and ``GITLAB_CI`` environments are
    plain. This does not look at logging or at ``quiet``.
    """
    target = sys.stderr if stream is None else stream
    if _notebook() or _ci() or _dumb_term() or not _tty(target):
        return "plain"
    return "interactive"


def _level(level: str | int) -> int:
    if isinstance(level, bool):
        raise ValidationError(
            "Logging level must be a name or a number.",
            operation="configure_logging",
        )
    if isinstance(level, int):
        return level
    if isinstance(level, str):
        value = getattr(logging, level.upper(), None)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    raise ValidationError(
        "Logging level must be a name or a number.",
        operation="configure_logging",
    )


def _owned_handler(logger: logging.Logger) -> _SdkHandler | None:
    for handler in logger.handlers:
        if isinstance(handler, _SdkHandler):
            return handler
    return None


def _application_handler_reachable(logger: logging.Logger) -> bool:
    current: logging.Logger | None = logger
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        for handler in current.handlers:
            if isinstance(handler, logging.NullHandler):
                continue
            if isinstance(handler, _SdkHandler):
                continue
            return True
        if not current.propagate:
            return False
        current = current.parent
    return False


def _extra_value(value: object) -> str | int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = plain_text(value)
        if text == "":
            return None
        return text
    return None


def _without_csi(value: str) -> str:
    cleaned: list[str] = []
    index = 0
    while index < len(value):
        if value[index] != "\x1b":
            cleaned.append(value[index])
            index += 1
            continue
        end = _csi_end(value, index)
        if end is None:
            index += 1
            continue
        index = end
    return "".join(cleaned)


def _csi_end(value: str, start: int) -> int | None:
    if start + 1 >= len(value) or value[start + 1] != "[":
        return None
    index = start + 2
    while index < len(value) and value[index] in "0123456789;?":
        index += 1
    if index < len(value) and value[index].isalpha():
        return index + 1
    return None


def _visible(char: str) -> bool:
    code = ord(char)
    return code >= 32 and code != 127


def _tty(stream: object) -> bool:
    isatty = getattr(stream, "isatty", None)
    if not callable(isatty):
        return False
    try:
        return bool(isatty())
    except (OSError, ValueError):
        return False


def _dumb_term() -> bool:
    return os.environ.get("TERM", "").strip().lower() in {"dumb", "unknown"}


def _ci() -> bool:
    return any(os.environ.get(name) for name in _CI)


def _notebook() -> bool:
    if os.environ.get("JPY_PARENT_PID"):
        return True
    if "ipykernel" in sys.modules:
        return True
    module = sys.modules.get("IPython.core.getipython")
    getter = getattr(module, "get_ipython", None) if module else None
    if not callable(getter):
        return False
    try:
        shell = getter()
    except Exception:
        return False
    if shell is None:
        return False
    return type(shell).__name__ != "TerminalInteractiveShell"
