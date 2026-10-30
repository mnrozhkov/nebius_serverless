"""Get, wait, and cancel against a fake transport and clock."""

from fakes import FakeClock, FakeTransport

import nebius_serverless as ns

SECRET = "super-secret-value"


def _run(
    fake: FakeTransport,
    *,
    states: list[str] | None = None,
) -> ns.Run:
    if states is not None:
        fake.states = states
    job = ns.Job(
        ["nvidia-smi"],
        image="python:3.12-slim",
        gpu="h100",
        timeout="1h",
        name="my-job",
        env={"TOKEN": SECRET},
    )
    created = job.create(
        region="eu-north1",
        project="project-1",
        transport=fake,
    )
    assert isinstance(created, ns.Run)
    return created


def _install_clock(monkeypatch: object, clock: FakeClock) -> None:
    patch = getattr(monkeypatch, "setattr")
    patch("nebius_serverless.run.monotonic", clock.monotonic)
    patch("nebius_serverless.run.sleep", clock.sleep)


def test_properties_do_not_fetch() -> None:
    fake = FakeTransport()
    run = _run(fake)
    assert run.id == "job-1"
    assert run.name == "my-job"
    assert run.status == "PROVISIONING"
    assert run.record is None
    assert fake.gets == []
    assert len(fake.bodies) == 1


def test_wait_reaches_a_terminal_state(monkeypatch: object) -> None:
    clock = FakeClock()
    _install_clock(monkeypatch, clock)
    fake = FakeTransport()
    run = _run(fake, states=["RUNNING", "COMPLETED"])
    record = run.wait()
    assert record["status"] == {"state": "COMPLETED"}
    assert run.status == "COMPLETED"
    assert run.record is record
    assert fake.gets == ["job-1", "job-1"]
    assert fake.cancels == []
    assert clock.now == 1.0


def test_wait_timeout_zero_does_not_cancel(monkeypatch: object) -> None:
    clock = FakeClock()
    _install_clock(monkeypatch, clock)
    fake = FakeTransport()
    run = _run(fake, states=["RUNNING"])
    try:
        run.wait(timeout=0)
    except ns.WaitTimeout as exc:
        assert exc.run_id == "job-1"
        assert SECRET not in str(exc)
    else:
        raise AssertionError("expected WaitTimeout")
    assert fake.gets == ["job-1"]
    assert fake.cancels == []
    assert clock.now == 0.0


def test_failed_and_cancelled_are_data() -> None:
    fake = FakeTransport()
    run = _run(fake, states=["FAILED"])
    failed = run.get()
    assert failed["status"] == {"state": "FAILED"}
    fake.states = ["CANCELLED"]
    cancelled = run.wait()
    assert cancelled["status"] == {"state": "CANCELLED"}
    payload = run.cancel()
    assert payload == {"id": "job-1", "accepted": True}
    assert fake.cancels == ["job-1"]


def test_jobs_get_reloads_without_creating() -> None:
    fake = FakeTransport()
    run = _run(fake, states=["COMPLETED"])
    loaded = ns.jobs.get(run.id, transport=fake)
    assert isinstance(loaded, ns.Run)
    assert loaded.id == run.id
    assert loaded.status == "COMPLETED"
    assert len(fake.bodies) == 1
    assert fake.gets == ["job-1"]


def test_raw_state_is_preserved() -> None:
    fake = FakeTransport()
    run = _run(fake, states=["ERROR"])
    record = run.wait(timeout=0)
    assert record["status"]["state"] == "ERROR"
    assert run.status == "ERROR"
