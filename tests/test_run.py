"""Get, wait, and cancel against a fake transport and clock."""

import io
import sys

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
    assert clock.now == 10.0


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


RECORD = {
    "metadata": {
        "id": "aijob-e00mk5q1t343gjj6dx",
        "parent_id": "project-e00sv054pr00ebm2dbq0ss",
        "name": "job-4a4d828fdc4e",
        "resource_version": "1",
        "created_at": "2026-11-02T10:28:34.155623Z",
        "updated_at": "2026-11-02T10:28:34.155623Z",
    },
    "spec": {
        "image": "nvidia/cuda:13.1.1-runtime-ubuntu24.04",
        "container_command": "nvidia-smi",
        "platform": "gpu-h100-sxm",
        "preset": "1gpu-16vcpu-200gb",
        "shm_size_bytes": "17179869184",
        "disk": {
            "type": "NETWORK_SSD",
            "size_bytes": "268435456000",
        },
        "subnet_id": "vpcsubnet-e00bzpvc489sap7znt",
        "timeout": "3600s",
        "env": {"TOKEN": SECRET},
    },
    "status": {
        "instances": [
            {
                "state": "COMPLETED",
                "compute_instance_id": (
                    "computeinstance-e00khhbp4n23bwhem0"
                ),
                "compute_instance_state": "RUNNING",
                "private_ip": "10.0.0.15",
            }
        ],
        "state": "COMPLETED",
        "started_at": "2026-11-02T10:30:46.163229611Z",
        "finished_at": "2026-11-02T10:30:49.163229611Z",
    },
}

DISPLAY = """\
aijob-e00mk5q1t343gjj6dx  job-4a4d828fdc4e
  COMPLETED

  image     nvidia/cuda:13.1.1-runtime-ubuntu24.04
  command   nvidia-smi
  platform  gpu-h100-sxm
  preset    1gpu-16vcpu-200gb
  disk      250 GiB NETWORK_SSD
  shm       16 GiB
  timeout   1h
  subnet    vpcsubnet-e00bzpvc489sap7znt

  created   2026-11-02 10:28:34Z
  started   2026-11-02 10:30:46Z
  finished  2026-11-02 10:30:49Z
  queued    2m 12s
  ran       3s

  instance  computeinstance-e00khhbp4n23bwhem0  10.0.0.15  COMPLETED
"""


class _TTY(io.StringIO):
    """In-memory stdout that claims to be a terminal."""

    encoding = "utf-8"

    def isatty(self) -> bool:
        return True


def test_display_prints_the_fetched_record(
    capsys: object,
    monkeypatch: object,
) -> None:
    monkeypatch.setenv("NO_COLOR", "1")  # type: ignore[attr-defined]
    fake = FakeTransport()
    run = ns.Run(
        "aijob-e00mk5q1t343gjj6dx",
        name="job-4a4d828fdc4e",
        transport=fake,
        record=RECORD,
    )
    run.display()
    out = capsys.readouterr().out  # type: ignore[attr-defined]
    assert out == DISPLAY
    assert SECRET not in out
    assert "project-e00sv054pr00ebm2dbq0ss" not in out
    assert fake.gets == []


def test_display_without_a_record_does_not_fetch(
    capsys: object,
) -> None:
    fake = FakeTransport()
    run = _run(fake)
    run.display()
    out = capsys.readouterr().out  # type: ignore[attr-defined]
    assert out == "job-1  my-job\n  no record yet\n"
    assert fake.gets == []


def test_display_colors_a_terminal(
    monkeypatch: object,
) -> None:
    patch = getattr(monkeypatch, "setattr")
    delete = getattr(monkeypatch, "delenv")
    setenv = getattr(monkeypatch, "setenv")
    for name in ("CI", "GITHUB_ACTIONS", "GITLAB_CI", "NO_COLOR"):
        delete(name, raising=False)
    setenv("TERM", "xterm")
    stream = _TTY()
    patch(sys, "stdout", stream)
    fake = FakeTransport()
    run = ns.Run(
        "aijob-e00mk5q1t343gjj6dx",
        name="job-4a4d828fdc4e",
        transport=fake,
        record=RECORD,
    )
    run.display()
    text = stream.getvalue()
    assert "\x1b[1;36m" in text
    assert "\x1b[1;32m" in text
    assert SECRET not in text
    failed = dict(RECORD)
    failed["status"] = {"state": "FAILED"}
    stream.seek(0)
    stream.truncate()
    ns.Run(
        "aijob-e00mk5q1t343gjj6dx",
        name="job-4a4d828fdc4e",
        transport=fake,
        record=failed,
    ).display()
    assert "\x1b[1;31m" in stream.getvalue()
