"""Synchronous calls refuse to run inside an event loop."""

import asyncio

from .errors import ValidationError


def reject_running_loop(twin: str) -> None:
    """Raise when a sync call is nested in a running event loop.

    The message names the awaited twin the caller should use.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    operation = twin.removesuffix("_async")
    raise ValidationError(
        "A synchronous call is inside a running event loop. "
        f"Use {twin}.",
        operation=operation,
    )
