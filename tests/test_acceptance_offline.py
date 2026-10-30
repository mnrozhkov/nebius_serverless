"""Offline checks of the example recipes."""

import ast
import json
import subprocess
import sys
from collections.abc import Callable, Sequence
from importlib.machinery import ModuleSpec
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

import pytest

import nebius_serverless as ns

ROOT = Path(__file__).parents[1]
EXAMPLES = ROOT / "examples"
CUDA = "nvidia/cuda:13.1.1-runtime-ubuntu24.04"
AXOLOTL = "docker.io/axolotlai/axolotl:main-20260309-py3.11-cu128-2.9.1"
REGION = "eu-north1"
PROJECT = "project-1"


def _load(path: Path) -> ModuleType:
    spec: ModuleSpec | None = spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _describe(job: ns.Job) -> dict[str, object]:
    described = job.create(
        dry_run=True,
        region=REGION,
        project=PROJECT,
    )
    assert isinstance(described, dict)
    return described


def _without_name(request: dict[str, object]) -> dict[str, object]:
    described = dict(request)
    described.pop("name", None)
    return described


def test_readme_points_at_the_contract() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "nebius==0.6.27" in text
    assert "from_yaml" in text
    assert "nebius ai job logs <id>" in text
    assert "specs/cloud-jobs.md" in text
    assert "run.get()" in text
    assert "run.wait()" in text
    assert "run.cancel()" in text
    assert "ns.jobs.get" in text
    assert "examples/job_quickstart.py" in text
    lowered = text.lower()
    assert "local backend" not in lowered
    assert "live nebius run" not in lowered


def test_examples_pass_gpu_aliases() -> None:
    skipped = {
        EXAMPLES / "official",
        EXAMPLES / "modal",
        EXAMPLES / "runpod",
    }
    for path in EXAMPLES.rglob("*"):
        if any(parent in skipped for parent in path.parents):
            continue
        if path.suffix not in {".py", ".yaml"}:
            continue
        text = path.read_text(encoding="utf-8")
        assert "platform=" not in text
        assert "preset=" not in text
        assert "\nplatform:" not in text
        assert "\npreset:" not in text


def test_nvidia_smi_matches_the_readme_and_the_yaml() -> None:
    quick = _load(EXAMPLES / "job_quickstart.py")
    job = ns.Job(
        quick.COMMAND,
        image=quick.IMAGE,
        gpu=quick.GPU,
        timeout=quick.TIMEOUT,
    )
    from_file = ns.Job.from_yaml(
        EXAMPLES / "from_yaml" / "nvidia_smi.yaml",
    )
    python_request = _describe(job)
    yaml_request = _describe(from_file)
    assert _without_name(python_request) == _without_name(yaml_request)
    assert python_request["image"] == CUDA
    assert python_request["command"] == ["nvidia-smi"]
    assert "args" not in python_request
    assert python_request["platform"] == "gpu-h100-sxm"
    assert python_request["preset"] == "1gpu-16vcpu-200gb"
    assert python_request["timeout"] == 3600
    assert python_request["pricing"] == "on-demand"
    assert python_request["disk"] == "250Gi"
    assert python_request["shm"] == "16Gi"


def test_axolotl_recipe() -> None:
    module = _load(EXAMPLES / "train" / "axolotl_lora.py")
    job = ns.Job(
        module.COMMAND,
        image=module.IMAGE,
        gpu=module.GPU,
        pricing="spot",
        disk="500Gi",
        timeout="24h",
    )
    request = _describe(job)
    assert request["image"] == AXOLOTL
    assert request["platform"] == "gpu-h100-sxm"
    assert request["preset"] == "1gpu-16vcpu-200gb"
    assert request["pricing"] == "spot"
    assert request["disk"] == "500Gi"
    assert request["timeout"] == 24 * 3600
    assert request["shm"] == "16Gi"
    assert "volumes" not in request


class _Clock:
    def __init__(self) -> None:
        self.now = 1_000.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds
        if len(self.sleeps) > 40:
            raise AssertionError("retrieval retry was not bounded")


class _Run:
    def __init__(
        self,
        job_id: str,
        status: str,
        *,
        events: list[tuple[object, ...]],
        size: int,
        raise_wait: bool,
    ) -> None:
        self.id = job_id
        self.status: str | None = None
        self._status = status
        self._events = events
        self._size = size
        self._raise_wait = raise_wait

    def wait(self, timeout: float | None = None) -> dict[str, object]:
        self._events.append(("wait", self._size, self.id, timeout))
        if self._raise_wait:
            raise ns.WaitTimeout(
                "local wait stopped",
                operation="wait",
                run_id=self.id,
            )
        self.status = self._status
        return {"status": {"state": self._status}}


def _report(size: int) -> dict[str, object]:
    return {
        "schema_version": 1,
        "size": size,
        "gpu": "NVIDIA H100",
        "elapsed_ms": size,
        "mean": -size,
        "verified": True,
    }


def _install(
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
    *,
    status_of: Callable[[int], str] | None = None,
    fail_create: set[int] | None = None,
    raise_wait: set[int] | None = None,
    stdout_for: Callable[[int], str] | None = None,
    on_aws: Callable[[Sequence[str]], None] | None = None,
    clock: _Clock | None = None,
) -> tuple[list[tuple[object, ...]], list[ns.Job]]:
    events: list[tuple[object, ...]] = []
    jobs: list[ns.Job] = []
    failed = fail_create or set()
    waiting = raise_wait or set()

    def create(self: ns.Job, *_args: object, **_kwargs: object) -> _Run:
        size = int(self.command[-1])
        events.append(("create", size))
        jobs.append(self)
        if size in failed:
            raise RuntimeError("quota")
        status = "COMPLETED" if status_of is None else status_of(size)
        return _Run(
            f"job-{size}",
            status,
            events=events,
            size=size,
            raise_wait=size in waiting,
        )

    def aws(
        args: Sequence[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        recorded = tuple(args)
        events.append(("aws", recorded, kwargs.get("timeout")))
        if on_aws is not None:
            on_aws(recorded)
        uri = recorded[3]
        assert isinstance(uri, str)
        size = int(uri.rsplit("/", 1)[-1].removesuffix(".json"))
        stdout = json.dumps(_report(size))
        if stdout_for is not None:
            stdout = stdout_for(size)
        return subprocess.CompletedProcess(
            list(args),
            0,
            stdout=stdout,
            stderr="",
        )

    monkeypatch.setattr(module.ns.Job, "create", create)
    monkeypatch.setattr(module.subprocess, "run", aws)
    if clock is not None:
        monkeypatch.setattr(module.time, "monotonic", clock.monotonic)
        monkeypatch.setattr(module.time, "sleep", clock.sleep)
    return events, jobs


def _matrix() -> ModuleType:
    return _load(EXAMPLES / "batch" / "matrix_multiply.py")


def test_matrix_import_is_idle(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def run(*_args: object, **_kwargs: object) -> None:
        calls.append("run")

    def create(self: ns.Job, *_args: object, **_kwargs: object) -> None:
        calls.append("create")
        raise AssertionError("create during import")

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(ns.Job, "create", create)
    module = _matrix()
    assert calls == []
    assert "torch" not in sys.modules
    tree = ast.parse((EXAMPLES / "batch" / "matrix_multiply.py").read_text())
    imported: list[str | None] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module)
    assert "torch" not in imported
    ast.parse(module.WORKER)


def test_worker_names_the_matrix_computation() -> None:
    module = _matrix()
    tree = ast.parse(module.WORKER)
    defined = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }
    function = defined["matrix_multiply"]
    assert [arg.arg for arg in function.args.args] == ["size"]
    allow_tf32_disabled = False
    highest_precision = False
    seed = False
    lists: list[list[object]] = []
    close = False
    no_grad = 0
    strict_json = False
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Attribute)
                and target.attr == "allow_tf32"
                for target in node.targets
            )
            and isinstance(node.value, ast.Constant)
            and node.value.value is False
        ):
            allow_tf32_disabled = True
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "set_float32_matmul_precision"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "highest"
        ):
            highest_precision = True
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "manual_seed"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == 42
        ):
            seed = True
        if isinstance(node, ast.List) and all(
            isinstance(item, ast.Constant) for item in node.elts
        ):
            lists.append([item.value for item in node.elts])
        if isinstance(node, ast.Call):
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "no_grad"
            ):
                no_grad += 1
            if node.func and any(
                keyword.arg == "allow_nan"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is False
                for keyword in node.keywords
            ):
                strict_json = True
            if any(
                keyword.arg == "rtol"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value == 1e-4
                for keyword in node.keywords
            ) and any(
                keyword.arg == "atol"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value == 1e-3
                for keyword in node.keywords
            ):
                close = True
    assert allow_tf32_disabled
    assert highest_precision
    assert seed
    assert [19.0, 22.0] in lists
    assert [43.0, 50.0] in lists
    assert no_grad >= 1
    assert close
    assert strict_json


def test_matrix_jobs_are_submitted_before_any_wait(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _matrix()
    events, jobs = _install(monkeypatch, module)
    module.main()
    out = capsys.readouterr().out
    assert module.SIZES == (1024, 2048, 4096)
    assert module.GPU == "h100"
    assert module.TIMEOUT == "1h"
    assert module.IMAGE == (
        "pytorch/pytorch@sha256:"
        "f894dae26e1ee8557c544f9cfdb9dc011b1552bf3c1e656b422f2e221d380e40"
    )
    assert module.ENDPOINT == "https://storage.eu-north1.nebius.cloud"
    assert [event[0] for event in events].index("wait") == 3
    assert [event[1] for event in events if event[0] == "create"] == [
        1024,
        2048,
        4096,
    ]
    prefix = jobs[0].command[3]
    assert prefix.startswith("matrix-multiply/")
    assert prefix.count("/") == 1
    volume = f"s3://{module.BUCKET}:/data:rw"
    uris: list[str] = []
    for job, size in zip(jobs, module.SIZES, strict=True):
        assert job.command == (
            "python",
            "-c",
            module.WORKER,
            prefix,
            str(size),
        )
        assert job.image == module.IMAGE
        assert job.gpu == "h100"
        assert job.timeout_seconds == 3600
        assert job.pricing == "on-demand"
        assert job.volumes == (volume,)
        wait = next(
            event
            for event in events
            if event[0] == "wait" and event[1] == size
        )
        fetch = next(
            event
            for event in events
            if event[0] == "aws" and str(event[1][3]).endswith(f"/{size}.json")
        )
        assert events.index(wait) > events.index(("create", size))
        assert events.index(fetch) > events.index(wait)
        assert wait[3] == 5400
        assert fetch[1][5:7] == ("--endpoint-url", module.ENDPOINT)
        timeout = fetch[2]
        assert isinstance(timeout, (int, float))
        assert 0 < timeout <= module.REPORT_SECONDS
        uri = fetch[1][3]
        assert isinstance(uri, str)
        uris.append(uri)
    assert len(set(uris)) == 3
    root = f"s3://{module.BUCKET}/{prefix}/"
    assert all(uri.startswith(root) for uri in uris)
    assert "size\tgpu\telapsed_ms\tmean\tverified" in out
    for size in module.SIZES:
        assert f"size {size}: job-{size}" in out
        assert f"{size}\tNVIDIA H100\t{size}\t{-size}\tTrue" in out
        assert out.index(f"size {size}: job-{size}") < out.index("size\tgpu")

    module.main()
    second = {job.command[3] for job in jobs[3:]}
    assert second != {prefix}
    assert len(second) == 1


def test_failed_job_is_not_fetched(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _matrix()
    events, _jobs = _install(
        monkeypatch,
        module,
        status_of=lambda size: "FAILED" if size == 2048 else "COMPLETED",
    )
    with pytest.raises(SystemExit, match="2048") as caught:
        module.main()
    message = str(caught.value)
    assert "job-2048" in message
    assert "FAILED" in message
    fetched = [
        event[1][3]
        for event in events
        if event[0] == "aws"
    ]
    assert fetched == [
        f"s3://{module.BUCKET}/{_jobs[0].command[3]}/1024.json"
    ]
    assert "size 1024: job-1024" in capsys.readouterr().out


def test_later_submission_failure_does_not_resubmit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _matrix()
    events, _jobs = _install(monkeypatch, module, fail_create={2048})
    with pytest.raises(SystemExit, match="submission failed") as caught:
        module.main()
    assert "2048" in str(caught.value)
    assert [event[1] for event in events if event[0] == "create"] == [
        1024,
        2048,
    ]
    assert not any(event[0] == "wait" for event in events)
    out = capsys.readouterr().out
    assert "job-1024" in out
    assert "job-2048" not in out


def test_local_wait_timeout_names_the_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _matrix()
    events, _jobs = _install(monkeypatch, module, raise_wait={1024})
    with pytest.raises(SystemExit, match="1024") as caught:
        module.main()
    message = str(caught.value)
    assert "job-1024" in message
    assert not any(event[0] == "aws" for event in events)


@pytest.mark.parametrize(
    ("sizes", "fragment"),
    [
        ((1024, 1024), "duplicate"),
        ((0, 2048), "positive"),
        ((-3,), "positive"),
        ((True, 1024), "positive"),
    ],
)
def test_bad_sizes_submit_nothing(
    monkeypatch: pytest.MonkeyPatch,
    sizes: tuple[object, ...],
    fragment: str,
) -> None:
    module = _matrix()
    events, _jobs = _install(monkeypatch, module)
    module.SIZES = sizes
    with pytest.raises(SystemExit, match=fragment):
        module.main()
    assert events == []


def _bad_stdout(case: str, size: int) -> str:
    report = _report(size)
    if case == "drop-size":
        report.pop("size")
        return json.dumps(report)
    if case == "wrong-size":
        report["size"] = 7
        return json.dumps(report)
    if case == "bool-elapsed":
        report["elapsed_ms"] = True
        return json.dumps(report)
    if case == "bool-mean":
        report["mean"] = True
        return json.dumps(report)
    if case == "bool-schema":
        report["schema_version"] = True
        return json.dumps(report)
    if case == "false-verified":
        report["verified"] = False
        return json.dumps(report)
    text = json.dumps(report)
    if case == "inf-elapsed":
        return text.replace(
            f'"elapsed_ms": {size}',
            '"elapsed_ms": 1e309',
            1,
        )
    if case == "nan":
        return text.replace(
            f'"elapsed_ms": {size}',
            '"elapsed_ms": NaN',
            1,
        )
    raise AssertionError(case)


@pytest.mark.parametrize(
    ("case", "kind"),
    [
        ("drop-size", "invalid"),
        ("wrong-size", "invalid"),
        ("bool-elapsed", "invalid"),
        ("bool-mean", "invalid"),
        ("bool-schema", "invalid"),
        ("false-verified", "invalid"),
        ("inf-elapsed", "invalid"),
        ("nan", "malformed"),
    ],
)
def test_invalid_reports_fail_without_retry(
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    kind: str,
) -> None:
    module = _matrix()
    clock = _Clock()
    events, _jobs = _install(
        monkeypatch,
        module,
        stdout_for=lambda size: _bad_stdout(case, size),
        clock=clock,
    )
    with pytest.raises(SystemExit, match=kind) as caught:
        module.main()
    message = str(caught.value)
    assert "1024" in message
    assert "job-1024" in message
    assert [event[0] for event in events if event[0] == "aws"] == ["aws"]
    assert clock.sleeps == []


def test_missing_object_retries_are_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _matrix()
    clock = _Clock()

    def on_aws(_args: Sequence[str]) -> None:
        raise subprocess.CalledProcessError(
            1,
            ["aws"],
            stderr=(
                "An error occurred (404) when calling the "
                "HeadObject operation: Not Found"
            ),
        )

    events, _jobs = _install(
        monkeypatch,
        module,
        on_aws=on_aws,
        clock=clock,
    )
    with pytest.raises(SystemExit, match="report missing") as caught:
        module.main()
    assert "job-1024" in str(caught.value)
    timeouts = [event[2] for event in events if event[0] == "aws"]
    attempts = module.REPORT_SECONDS // module.REPORT_PAUSE
    assert timeouts[0] == module.REPORT_SECONDS
    assert timeouts[-1] == module.REPORT_PAUSE
    assert len(timeouts) == attempts
    assert clock.sleeps == [module.REPORT_PAUSE] * (attempts - 1)


def test_access_and_ambiguous_errors_are_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _matrix()
    clock = _Clock()
    stderrs = [
        "An error occurred (403) when calling the "
        "HeadObject operation: Forbidden",
        "The config profile (default) could not be found",
        "",
    ]

    def on_aws(_args: Sequence[str]) -> None:
        raise subprocess.CalledProcessError(1, ["aws"], stderr=stderrs.pop(0))

    events, _jobs = _install(
        monkeypatch,
        module,
        on_aws=on_aws,
        clock=clock,
    )
    with pytest.raises(SystemExit, match="cannot retrieve") as caught:
        module.main()
    assert "403" in str(caught.value)
    assert "job-1024" in str(caught.value)
    assert len([event for event in events if event[0] == "aws"]) == 1
    assert clock.sleeps == []

    events.clear()
    with pytest.raises(SystemExit, match="could not be found"):
        module.main()
    assert len([event for event in events if event[0] == "aws"]) == 1
    assert clock.sleeps == []

    events.clear()
    with pytest.raises(SystemExit, match="cannot retrieve"):
        module.main()
    assert len([event for event in events if event[0] == "aws"]) == 1
    assert clock.sleeps == []


def test_a_late_missing_object_can_still_succeed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _matrix()
    clock = _Clock()
    misses = {"left": 2}

    def on_aws(_args: Sequence[str]) -> None:
        if misses["left"] <= 0:
            return
        misses["left"] -= 1
        raise subprocess.CalledProcessError(
            1,
            ["aws"],
            stderr="404 NoSuchKey",
        )

    _install(monkeypatch, module, on_aws=on_aws, clock=clock)
    module.main()
    assert clock.sleeps == [module.REPORT_PAUSE, module.REPORT_PAUSE]
    assert "4096\tNVIDIA H100\t4096\t-4096\tTrue" in capsys.readouterr().out
