"""Automatic progress, per-call quiet, and diagnostics."""

import asyncio
import io
import json
import logging
import os
import select
import subprocess
import sys
import threading
import time
import types
from collections.abc import Mapping

import pytest
from fakes import FakeClock, FakeTransport

import nebius_serverless as ns
from nebius_serverless.errors import exposed_request_id
from nebius_serverless.output import _coordinator
from nebius_serverless.transport import CreateResult, finish_create

SECRET = "super-secret-value"
MARKER = "payload-marker"
CUDA = "nvidia/cuda:13.1.1-runtime-ubuntu24.04"


class _TTY(io.StringIO):
    """In-memory stderr that claims to be a terminal."""

    encoding = "utf-8"

    def isatty(self) -> bool:
        return True


class _ASCII(io.StringIO):
    """In-memory stderr that cannot encode the spinner marks."""

    encoding = "ascii"


@pytest.fixture(autouse=True)
def _isolate_logging() -> object:
    logger = logging.getLogger("nebius_serverless")
    root = logging.getLogger()
    saved = (
        logger.level,
        logger.propagate,
        list(logger.handlers),
        root.level,
        list(root.handlers),
    )
    yield
    logger.setLevel(saved[0])
    logger.propagate = saved[1]
    logger.handlers[:] = saved[2]
    root.setLevel(saved[3])
    root.handlers[:] = saved[4]
    with _coordinator.lock:
        for handle in list(_coordinator._waits.values()):
            handle.close()
        _coordinator._waits.clear()


def _job(**kwargs: object) -> ns.Job:
    fields: dict[str, object] = {
        "image": "python:3.12-slim",
        "gpu": "h100",
        "timeout": "1h",
        "name": "my-job",
        "env": {"TOKEN": SECRET},
    }
    fields.update(kwargs)
    command = fields.pop("command", ["nvidia-smi"])
    return ns.Job(command, **fields)  # type: ignore[arg-type]


def _create(
    fake: FakeTransport,
    *,
    quiet: bool = False,
    **kwargs: object,
) -> ns.Run:
    created = _job(**kwargs).create(
        region="eu-north1",
        project="project-1",
        transport=fake,
        quiet=quiet,
    )
    assert isinstance(created, ns.Run)
    return created


def _named(job_id: str, states: list[str]) -> FakeTransport:
    fake = FakeTransport()
    fake.states = states

    def create(body: Mapping[str, object]) -> CreateResult:
        fake.bodies.append(dict(body))
        return CreateResult(
            resource_id=job_id,
            accepted=True,
            state="PROVISIONING",
        )

    fake.create = create  # type: ignore[method-assign]
    return fake


def _clock(monkeypatch: pytest.MonkeyPatch, clock: FakeClock) -> None:
    monkeypatch.setattr("nebius_serverless.run.monotonic", clock.monotonic)
    monkeypatch.setattr("nebius_serverless.run.sleep", clock.sleep)


def _terminal(monkeypatch: pytest.MonkeyPatch, stream: io.StringIO) -> None:
    monkeypatch.setattr(sys, "stderr", stream)
    monkeypatch.setenv("TERM", "xterm-256color")
    for name in ("CI", "GITHUB_ACTIONS", "GITLAB_CI", "JPY_PARENT_PID"):
        monkeypatch.delenv(name, raising=False)


def _has_key(value: object, key: str) -> bool:
    if isinstance(value, dict):
        if key in value:
            return True
        return any(_has_key(item, key) for item in value.values())
    if isinstance(value, list):
        return any(_has_key(item, key) for item in value)
    return False


def test_import_writes_nothing() -> None:
    code = "\n".join(
        (
            "import sys",
            "import nebius_serverless as ns",
            "assert 'rich' not in sys.modules",
            "import logging",
            "logger = logging.getLogger('nebius_serverless')",
            "assert logger.propagate is True",
            "names = [type(h).__name__ for h in logger.handlers]",
            "assert names == ['NullHandler']",
            "assert 'output' not in ns.__all__",
        )
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == ""
    assert completed.stderr == ""


def test_dry_run_stays_silent(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import rich.console as rich_console

    calls: list[object] = []
    original = rich_console.Console

    def capture(*args: object, **kwargs: object) -> object:
        calls.append(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(rich_console, "Console", capture)
    described = _job().create(
        dry_run=True,
        region="eu-north1",
        project="project-1",
    )
    assert isinstance(described, dict)
    assert calls == []
    assert capsys.readouterr().err == ""


def test_default_calls_show_progress(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    _clock(monkeypatch, clock)
    fake = FakeTransport()
    fake.states = ["RUNNING", "RUNNING", "COMPLETED"]
    run = _create(fake)
    created = capsys.readouterr().err
    assert created == "Submitted job job-1 my-job · PROVISIONING\n"
    assert run.get()["status"] == {"state": "RUNNING"}
    snapshot = capsys.readouterr().err
    assert snapshot == "job-1 RUNNING\n"
    assert run.wait()["status"] == {"state": "COMPLETED"}
    waited = capsys.readouterr().err
    assert "job-1 RUNNING · observed for 0s\n" in waited
    assert waited.count("RUNNING") == 1
    assert "✓ job-1 COMPLETED · observed for 1s\n" in waited
    assert "\x1b" not in waited
    payload = run.cancel()
    assert payload["accepted"] is True
    assert capsys.readouterr().err == "Cancel accepted for job-1\n"
    loaded = ns.jobs.get(run.id, transport=fake)
    assert loaded.id == run.id
    assert capsys.readouterr().err == "job-1 COMPLETED\n"
    assert fake.cancels == ["job-1"]
    assert not _has_key(fake.bodies[0], "quiet")


def test_quiet_is_per_call(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    _clock(monkeypatch, clock)
    fake = FakeTransport()
    fake.states = ["COMPLETED"]
    run = _create(fake, quiet=True)
    assert capsys.readouterr().err == ""
    assert "quiet" not in vars(run)
    record = run.wait()
    assert record["status"] == {"state": "COMPLETED"}
    assert "COMPLETED" in capsys.readouterr().err
    run.wait(quiet=True)
    assert capsys.readouterr().err == ""


def test_quiet_on_each_sync_call(
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake = FakeTransport()
    fake.states = ["FAILED"]
    run = _create(fake, quiet=True)
    assert run.get(quiet=True)["status"] == {"state": "FAILED"}
    assert run.wait(timeout=0, quiet=True)["status"] == {"state": "FAILED"}
    assert run.cancel(quiet=True)["accepted"] is True
    loaded = ns.jobs.get(run.id, transport=fake, quiet=True)
    assert loaded.status == "FAILED"
    assert capsys.readouterr().err == ""
    assert not _has_key(fake.bodies[0], "quiet")


def test_quiet_on_each_async_call(
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake = FakeTransport()
    fake.states = ["COMPLETED"]
    job = _job()

    async def follow() -> None:
        created = await job.create_async(
            region="eu-north1",
            project="project-1",
            transport=fake,
            quiet=True,
        )
        assert isinstance(created, ns.Run)
        await created.get_async(quiet=True)
        await created.wait_async(timeout=0, quiet=True)
        await created.cancel_async(quiet=True)
        loaded = await ns.jobs.get_async(
            created.id,
            transport=fake,
            quiet=True,
        )
        assert loaded.id == created.id

    asyncio.run(follow())
    assert capsys.readouterr().err == ""

    async def loud() -> None:
        await job.create_async(
            region="eu-north1",
            project="project-1",
            transport=fake,
        )

    asyncio.run(loud())
    assert "Submitted job" in capsys.readouterr().err


def test_quiet_still_raises_and_logs(
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import rich.console as rich_console

    def boom(*args: object, **kwargs: object) -> object:
        raise AssertionError("console")

    monkeypatch.setattr(rich_console, "Console", boom)
    caplog.set_level(logging.DEBUG, logger="nebius_serverless")
    ns.configure_logging(level="DEBUG")
    fake = FakeTransport()
    fake.states = ["RUNNING"]
    run = _create(fake, quiet=True)
    with pytest.raises(ns.WaitTimeout) as caught:
        run.wait(timeout=0, quiet=True)
    text = str(caught.value)
    assert text == (
        "Stopped waiting for job-1 after 0s.\n"
        "The job may still be running remotely.\n"
        "Reload it with jobs.get(id), "
        "or explicitly request cancellation."
    )
    assert "job-1" in text
    err = capsys.readouterr().err
    assert "Stopped waiting" not in err
    polls = [
        record
        for record in caplog.records
        if record.getMessage() == "Polled job"
    ]
    assert polls
    assert polls[0].event == "poll"  # type: ignore[attr-defined]
    assert polls[0].operation_id  # type: ignore[attr-defined]
    assert getattr(polls[0], "request_id", None) in (None, "")
    assert any(
        record.getMessage() == "Local waiting ended"
        for record in caplog.records
    )
    assert SECRET not in caplog.text
    assert SECRET not in err


def test_wait_timeout_text_and_get_count(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    _clock(monkeypatch, clock)
    fake = FakeTransport()
    fake.states = ["RUNNING"]
    run = _create(fake, quiet=True)
    with pytest.raises(ns.WaitTimeout) as caught:
        run.wait(timeout=2)
    assert str(caught.value) == (
        "Stopped waiting for job-1 after 2s.\n"
        "The job may still be running remotely.\n"
        "Reload it with jobs.get(id), "
        "or explicitly request cancellation."
    )
    assert caught.value.code == "wait_timeout"
    assert "cancel" in caught.value.recovery
    assert fake.gets == ["job-1", "job-1"]
    assert fake.cancels == []
    err = capsys.readouterr().err
    assert err.count("Stopped waiting for job-1 after 2s.") == 1
    assert "The job may still be running remotely." in err
    assert "or explicitly request cancellation." in err
    assert "job-1 RUNNING · observed for 0s\n" in err
    assert SECRET not in err


def test_unchanged_polls_print_one_summary(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    _clock(monkeypatch, clock)
    fake = FakeTransport()
    fake.states = ["RUNNING", "RUNNING", "RUNNING", "COMPLETED"]
    run = _create(fake, quiet=True)
    run.wait()
    err = capsys.readouterr().err
    assert fake.gets == ["job-1", "job-1", "job-1", "job-1"]
    assert err.count("RUNNING") == 1
    assert err.count("COMPLETED") == 1
    assert "->" not in err


def test_first_observation_terminal_is_summary_only(
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake = FakeTransport()
    fake.states = ["COMPLETED"]
    run = _create(fake, quiet=True)
    run.wait(timeout=0)
    err = capsys.readouterr().err
    assert err.count("COMPLETED") == 1
    assert "->" not in err
    assert "observed for" in err
    failed = FakeTransport()
    failed.states = ["FAILED"]
    run = _create(failed, quiet=True)
    assert run.wait(timeout=0)["status"] == {"state": "FAILED"}
    err = capsys.readouterr().err
    assert err == (
        "✗ job-1 FAILED\n"
        "  Reload it with jobs.get(id). "
        "Do not send a second create.\n"
    )


def test_markup_and_controls_stay_on_one_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    name = "pre[bold]\x1b[31mred[/bold]\nnext"
    fake = FakeTransport()
    run = _create(fake, name=name, command=[MARKER])
    err = capsys.readouterr().err
    assert err.count("\n") == 1
    assert "[bold]" in err
    assert "\x1b" not in err
    assert "\nnext" not in err
    assert MARKER not in err
    assert SECRET not in err
    assert run.id in err


def test_ascii_markers(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = _ASCII()
    monkeypatch.setattr(sys, "stderr", stream)
    fake = FakeTransport()
    fake.states = ["FAILED"]
    run = _create(fake, quiet=True)
    run.wait(timeout=0)
    text = stream.getvalue()
    assert "✓" not in text
    assert "✗" not in text
    assert "·" not in text
    assert text.startswith("x job-1 FAILED\n")


def test_secrets_stay_out_of_progress_and_logs(
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="nebius_serverless")
    ns.configure_logging(level="DEBUG")
    fake = FakeTransport()
    _create(fake, command=[MARKER])
    err = capsys.readouterr().err
    logged = caplog.text + "".join(
        str(getattr(record, key, ""))
        for record in caplog.records
        for key in (
            "event",
            "operation_id",
            "request_id",
            "job_id",
            "attempt",
            "duration_ms",
            "status_code",
        )
    )
    assert SECRET not in err
    assert MARKER not in err
    assert SECRET not in logged
    assert MARKER not in logged

    def get(job_id: str) -> dict[str, object]:
        raise RuntimeError(f"{SECRET} {MARKER} raw body")

    fake.get = get  # type: ignore[method-assign]
    run = _create(fake, quiet=True)
    capsys.readouterr()
    with pytest.raises(RuntimeError):
        run.get()
    leaked = capsys.readouterr().err
    assert SECRET not in leaked
    assert MARKER not in leaked
    assert "raw body" not in leaked


def test_interactive_plain_color_and_ci(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import rich.console as rich_console

    seen: list[dict[str, object]] = []
    console_type = rich_console.Console

    def capture(*args: object, **kwargs: object) -> object:
        seen.append(dict(kwargs))
        return console_type(*args, **kwargs)

    monkeypatch.setattr(rich_console, "Console", capture)
    stream = _TTY()
    _terminal(monkeypatch, stream)
    monkeypatch.setenv("NO_COLOR", "1")
    clock = FakeClock()
    _clock(monkeypatch, clock)
    fake = _named("aijob-123", ["RUNNING", "COMPLETED"])
    fetch = fake.get

    def get(job_id: str) -> dict[str, object]:
        if clock.now == 0.0:
            clock.now = 1.0
        return fetch(job_id)

    fake.get = get  # type: ignore[method-assign]
    run = _create(fake, quiet=True, name="my-job")
    run.wait()
    text = stream.getvalue()
    assert "\x1b" in text
    assert "aijob-123" in text
    assert "COMPLETED" in text
    assert "\x1b[31" not in text
    assert seen
    assert all(item.get("no_color") is True for item in seen)

    stream = _TTY()
    _terminal(monkeypatch, stream)
    monkeypatch.delenv("NO_COLOR", raising=False)
    seen.clear()
    _create(_named("aijob-color", ["RUNNING"]))
    colored = stream.getvalue()
    assert seen[-1]["no_color"] is None
    assert "aijob-color" in colored
    assert "\x1b[1;36m" in colored
    assert "\x1b[33m" in colored

    plain = io.StringIO()
    monkeypatch.setattr(sys, "stderr", plain)
    _create(_named("aijob-plain", ["RUNNING"]), quiet=False)
    assert "\x1b" not in plain.getvalue()

    stream = _TTY()
    _terminal(monkeypatch, stream)
    monkeypatch.setenv("CI", "true")
    _create(_named("aijob-ci", ["RUNNING"]))
    assert "\x1b" not in stream.getvalue()


@pytest.mark.parametrize("name", ["GITHUB_ACTIONS", "GITLAB_CI"])
def test_ci_variables_are_plain(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    stream = _TTY()
    _terminal(monkeypatch, stream)
    monkeypatch.setenv(name, "true")
    _create(_named("aijob-ci", ["RUNNING"]))
    assert "\x1b" not in stream.getvalue()


def test_notebook_is_plain(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = _TTY()
    _terminal(monkeypatch, stream)
    monkeypatch.setitem(
        sys.modules,
        "ipykernel",
        types.ModuleType("ipykernel"),
    )
    _create(_named("aijob-nb", ["RUNNING"]))
    assert "\x1b" not in stream.getvalue()
    assert ns.diagnostics()["presentation"] == "plain"


def test_cancelling_wait_async_prints_nothing_more(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nebius_serverless.output as output

    stream = _TTY()
    _terminal(monkeypatch, stream)
    monkeypatch.setattr("nebius_serverless.run.monotonic", lambda: 1.0)
    monkeypatch.setattr("nebius_serverless.run.sleep", lambda _seconds: None)
    started = threading.Event()
    release = threading.Event()
    rendered = threading.Event()
    calls = {"n": 0}
    fake = FakeTransport()

    def get(job_id: str) -> dict[str, object]:
        calls["n"] += 1
        if calls["n"] == 1:
            started.set()
            assert release.wait(5)
            state = "RUNNING"
        else:
            state = "COMPLETED"
        return {
            "metadata": {"id": job_id, "name": "saved"},
            "status": {"state": state},
        }

    fake.get = get  # type: ignore[method-assign]
    run = _create(fake, quiet=True)
    original = output.report

    def wrapped(fact: object, handle: object) -> None:
        original(fact, handle)  # type: ignore[arg-type]
        if calls["n"] >= 2:
            rendered.set()

    monkeypatch.setattr(output, "report", wrapped)

    async def cancel_wait() -> None:
        task = asyncio.create_task(run.wait_async())
        await asyncio.to_thread(started.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        release.set()
        assert await asyncio.to_thread(rendered.wait, 5)

    asyncio.run(cancel_wait())
    assert calls["n"] >= 2
    assert fake.cancels == []
    assert stream.getvalue() == ""


def test_overlapping_waits_and_a_later_spinner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = _TTY()
    _terminal(monkeypatch, stream)
    monkeypatch.setattr("nebius_serverless.run.sleep", lambda _seconds: None)
    barrier = threading.Barrier(2)

    def run_wait(job_id: str) -> None:
        fake = _named(job_id, ["RUNNING", "COMPLETED"])
        calls = {"n": 0}
        original = fake.get

        def get(jid: str) -> dict[str, object]:
            calls["n"] += 1
            if calls["n"] == 1:
                barrier.wait(5)
            return original(jid)

        fake.get = get  # type: ignore[method-assign]
        created = _create(fake, quiet=True)
        created.wait()

    threads = [
        threading.Thread(target=run_wait, args=(job_id,))
        for job_id in ("aijob-a", "aijob-b")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
        assert not thread.is_alive()
    overlapped = stream.getvalue()
    assert "\x1b" not in overlapped
    assert overlapped.count("aijob-a") >= 1
    assert overlapped.count("aijob-b") >= 1

    stream.seek(0)
    stream.truncate(0)
    clock = FakeClock()
    _clock(monkeypatch, clock)
    later_fake = _named("aijob-c", ["RUNNING", "COMPLETED"])
    original = later_fake.get

    def get(job_id: str) -> dict[str, object]:
        if clock.now == 0.0:
            clock.now = 1.0
        return original(job_id)

    later_fake.get = get  # type: ignore[method-assign]
    later = _create(later_fake, quiet=True)
    later.wait()
    solo = stream.getvalue()
    assert "\x1b" in solo
    assert "aijob-c" in solo


def test_quiet_wait_does_not_take_a_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = _TTY()
    _terminal(monkeypatch, stream)
    clock = FakeClock()
    _clock(monkeypatch, clock)
    started = threading.Event()
    release = threading.Event()
    fake = _named("aijob-visible", ["RUNNING", "COMPLETED"])
    calls = {"n": 0}
    original = fake.get

    def get(job_id: str) -> dict[str, object]:
        calls["n"] += 1
        if calls["n"] == 1:
            started.set()
            assert release.wait(5)
            clock.now = 1.0
        return original(job_id)

    fake.get = get  # type: ignore[method-assign]
    visible = _create(fake, quiet=True)

    def run_visible() -> None:
        visible.wait()

    thread = threading.Thread(target=run_visible)
    thread.start()
    assert started.wait(5)
    quiet = _create(_named("aijob-quiet", ["COMPLETED"]), quiet=True)
    quiet.wait(quiet=True)
    release.set()
    thread.join(5)
    assert not thread.is_alive()
    text = stream.getvalue()
    assert "aijob-quiet" not in text
    assert "aijob-visible" in text
    assert "\x1b" in text


def test_configure_logging_updates_one_handler() -> None:
    code = "\n".join(
        (
            "import logging",
            "import nebius_serverless as ns",
            "ns.configure_logging(level='INFO')",
            "log = logging.getLogger('nebius_serverless.job')",
            "log.debug('hidden-debug')",
            "log.info('visible-info')",
            "ns.configure_logging(level='DEBUG')",
            "log.debug(",
            "    'shown-debug',",
            "    extra={'event': 'poll', 'operation_id': 'abc'},",
            ")",
            "logger = logging.getLogger('nebius_serverless')",
            "owned = [",
            "    h for h in logger.handlers",
            "    if type(h).__name__ == '_SdkHandler'",
            "]",
            "assert len(owned) == 1",
            "assert logger.level == logging.DEBUG",
            "assert logger.propagate is False",
        )
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    err = completed.stderr
    assert "hidden-debug" not in err
    assert "visible-info" in err
    assert "shown-debug" in err
    assert "event=poll" in err
    assert "operation_id=abc" in err


def test_application_handler_is_left_alone() -> None:
    logger = logging.getLogger("nebius_serverless")
    stream = io.StringIO()
    app = logging.StreamHandler(stream)
    app.setLevel(logging.ERROR)
    app.addFilter(logging.Filter("nebius_serverless"))
    logger.addHandler(app)
    logger.propagate = True
    before = list(app.filters)
    ns.configure_logging(level="WARNING")
    assert app in logger.handlers
    assert app.level == logging.ERROR
    assert list(app.filters) == before
    assert logger.propagate is True
    assert logger.level == logging.WARNING
    owned = [
        handler
        for handler in logger.handlers
        if type(handler).__name__ == "_SdkHandler"
    ]
    assert owned == []
    logging.getLogger("nebius_serverless.run").error("once")
    assert stream.getvalue().count("once") == 1


def test_root_handler_receives_one_record() -> None:
    logger = logging.getLogger("nebius_serverless")
    root = logging.getLogger()
    stream = io.StringIO()
    root_handler = logging.StreamHandler(stream)
    root.addHandler(root_handler)
    root.setLevel(logging.DEBUG)
    before = list(logger.handlers)
    ns.configure_logging(level="INFO")
    assert logger.handlers == before
    assert logger.propagate is True
    logging.getLogger("nebius_serverless.job").info("rooted")
    assert stream.getvalue().count("rooted") == 1


def test_polls_share_one_operation_id(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    _clock(monkeypatch, clock)
    caplog.set_level(logging.DEBUG, logger="nebius_serverless")
    fake = FakeTransport()
    fake.states = ["RUNNING", "RUNNING", "COMPLETED"]
    run = _create(fake, quiet=True)
    caplog.clear()
    run.wait(quiet=True)
    found = [
        record.operation_id  # type: ignore[attr-defined]
        for record in caplog.records
        if getattr(record, "operation_id", None)
    ]
    assert len(found) >= 2
    assert len(set(found)) == 1
    caplog.clear()
    run.wait(quiet=True)
    again = [
        record.operation_id  # type: ignore[attr-defined]
        for record in caplog.records
        if getattr(record, "operation_id", None)
    ]
    assert again
    assert set(again).isdisjoint(found)


def test_error_codes_request_id_and_uncertain_create() -> None:
    assert ns.ValidationError("x").code == "validation"
    assert ns.UnsupportedFeature("x").code == "unsupported"
    assert ns.AccessError("x").code == "access"
    assert "profile" in ns.AccessError("x").recovery
    assert ns.CapacityError("x").code == "capacity"
    assert "capacity" in ns.CapacityError("x").recovery
    assert ns.TransportError("x").code == "transport"
    assert ns.KeyConflict("x").code == "key_conflict"
    assert "second create" in ns.KeyConflict("x").recovery
    same = ns.ValidationError("x").recovery
    assert ns.SubmissionUncertain("x").recovery == same
    assert ns.SubmissionUncertain("x").code == "submission_uncertain"
    assert "cancel" in ns.WaitTimeout("x").recovery
    assert ns.TransportError("x", request_id="  ").request_id is None

    class HasStatus(Exception):
        def __init__(self) -> None:
            status = types.SimpleNamespace(request_id="req-9")
            self.status = status

    assert exposed_request_id(HasStatus()) == "req-9"
    assert exposed_request_id(Exception("secret")) is None
    with pytest.raises(ns.SubmissionUncertain) as caught:
        finish_create(
            CreateResult(
                accepted=True,
                failure="uncertain",
                request_id="req-9",
            )
        )
    assert caught.value.request_id == "req-9"
    assert "second create" in caught.value.recovery

    fake = FakeTransport()
    fake.drop_id = True
    with pytest.raises(ns.SubmissionUncertain):
        _create(fake)
    assert len(fake.bodies) == 1


def test_diagnostics_is_local(monkeypatch: pytest.MonkeyPatch) -> None:
    data = ns.diagnostics()
    json.dumps(data)
    assert set(data) == {
        "version",
        "python",
        "platform",
        "presentation",
    }
    assert data["version"] == ns.__version__
    assert data["presentation"] == "plain"
    assert SECRET not in json.dumps(data)
    assert "rich" not in data
    stream = _TTY()
    _terminal(monkeypatch, stream)
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert ns.diagnostics()["presentation"] == "interactive"
    monkeypatch.setenv("TERM", "dumb")
    assert ns.diagnostics()["presentation"] == "plain"


def test_terminal_smoke() -> None:
    env = os.environ.copy()
    env["TERM"] = "xterm-256color"
    env["NO_COLOR"] = "1"
    for mode in ("fast", "change", "failed", "debug"):
        text = _pty(mode, env)
        assert "aijob-123" in text
        if mode == "debug":
            assert "\x1b" not in text
            assert "PROVISIONING" in text
            assert "RUNNING" in text
            assert "COMPLETED" in text
        if mode == "fast":
            assert "COMPLETED" in text
            assert "->" not in text
        if mode == "change":
            assert "PROVISIONING -> RUNNING" in text
            assert "COMPLETED" in text
        if mode == "failed":
            assert "FAILED" in text
            assert "Do not send a second create." in text
    interrupted = _pty("interrupt", env, sigint=True)
    assert "CANCELS 0" in interrupted
    assert "Cancel accepted" not in interrupted


def _pty(mode: str, env: dict[str, str], *, sigint: bool = False) -> str:
    import pty
    import signal

    master, slave = pty.openpty()
    proc = subprocess.Popen(
        [sys.executable, "-c", _SMOKE, mode],
        stdout=slave,
        stderr=slave,
        env=env,
        close_fds=True,
    )
    os.close(slave)
    chunks: list[bytes] = []
    sent = False
    deadline = time.monotonic() + 8
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([master], [], [], 0.2)
            if ready:
                try:
                    chunk = os.read(master, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                chunks.append(chunk)
                if (
                    sigint
                    and not sent
                    and b"READY" in b"".join(chunks)
                ):
                    proc.send_signal(signal.SIGINT)
                    sent = True
            if proc.poll() is not None:
                break
        else:
            proc.kill()
        proc.wait(timeout=5)
    finally:
        os.close(master)
    assert proc.returncode == 0, b"".join(chunks)
    return b"".join(chunks).decode()


_SMOKE = r"""
import sys
import time

import nebius_serverless as ns
from nebius_serverless.transport import CreateResult

mode = sys.argv[1]
clock = {"now": 0.0}

def monotonic():
    return clock["now"]

def sleep(seconds):
    clock["now"] += seconds

import nebius_serverless.run as run_mod
run_mod.monotonic = monotonic
run_mod.sleep = sleep

class Fake:
    def __init__(self, states):
        self.states = states
        self.i = 0
        self.cancels = []
        self.bodies = []

    def create(self, body):
        self.bodies.append(dict(body))
        return CreateResult(
            resource_id="aijob-123",
            accepted=True,
            state="PROVISIONING",
        )

    def get(self, job_id):
        if mode == "interrupt" and self.i == 0:
            self.i += 1
            print("READY", flush=True)
            time.sleep(30)
        state = self.states[min(self.i, len(self.states) - 1)]
        self.i += 1
        return {
            "metadata": {"id": job_id, "name": "my-job"},
            "status": {"state": state},
        }

    def cancel(self, job_id):
        self.cancels.append(job_id)
        return {"id": job_id, "accepted": True}

states = {
    "fast": ["COMPLETED"],
    "change": ["PROVISIONING", "RUNNING", "COMPLETED"],
    "failed": ["FAILED"],
    "debug": ["PROVISIONING", "RUNNING", "COMPLETED"],
    "interrupt": ["RUNNING"],
}[mode]
fake = Fake(states)
if mode == "debug":
    ns.configure_logging(level="DEBUG")
job = ns.Job(
    ["nvidia-smi"],
    image="python:3.12-slim",
    gpu="h100",
    timeout="1h",
    name="my-job",
)
run = job.create(
    region="eu-north1",
    project="project-1",
    transport=fake,
    quiet=True,
)
try:
    run.wait()
except KeyboardInterrupt:
    print("CANCELS %s" % len(fake.cancels), flush=True)
except Exception:
    print("CANCELS %s" % len(fake.cancels), flush=True)
    raise
"""
