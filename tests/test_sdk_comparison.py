"""Offline tests for the SDK comparison suite and measurement runner."""

from __future__ import annotations

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

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
COMPARISON_DIRS = (
    EXAMPLES / "comparison",
    EXAMPLES / "official",
    EXAMPLES / "batch",
    EXAMPLES / "modal",
    EXAMPLES / "runpod",
)


def _load_module(path: Path) -> ModuleType:
    spec: ModuleSpec | None = spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _extract_function_source(path: Path, func_name: str) -> str:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    lines = source.splitlines()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            assert node.lineno is not None and node.end_lineno is not None
            return "\n".join(lines[node.lineno - 1 : node.end_lineno])
    raise AssertionError(f"{func_name} not found in {path}")


def _extract_constant_str(path: Path, const_name: str) -> str:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(
            isinstance(target, ast.Name) and target.id == const_name
            for target in node.targets
        ):
            assert isinstance(node.value, ast.Constant)
            assert isinstance(node.value.value, str)
            return node.value.value
    raise AssertionError(f"{const_name} not found in {path}")


def test_all_comparison_python_files_parse_without_importing_competitors() -> (
    None
):
    py_files: list[Path] = []
    for folder in COMPARISON_DIRS:
        found = sorted(folder.rglob("*.py"))
        assert found, f"No Python files found in {folder}"
        py_files.extend(found)

    for path in py_files:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        assert isinstance(tree, ast.Module)

    assert "modal" not in sys.modules
    assert "runpod" not in sys.modules


def test_embedded_workers_match_canonical_worker_verbatim() -> None:
    canonical_path = EXAMPLES / "comparison" / "worker.py"
    canonical_worker = _extract_constant_str(canonical_path, "WORKER")
    canonical_fn = _extract_function_source(canonical_path, "matrix_multiply")

    for script_rel in (
        "examples/batch/matrix_multiply.py",
        "examples/official/matrix_multiply.py",
    ):
        script_path = ROOT / script_rel
        embedded_worker = _extract_constant_str(script_path, "WORKER")
        assert embedded_worker == canonical_worker, (
            f"WORKER mismatch in {script_rel}"
        )
        assert canonical_fn in embedded_worker
        assert "examples.comparison" not in script_path.read_text(
            encoding="utf-8"
        )

    for script_rel in (
        "examples/modal/matrix_multiply.py",
        "examples/runpod/app/matrix_multiply.py",
        "examples/runpod/endpoint/matrix_worker.py",
    ):
        script_path = ROOT / script_rel
        fn_source = _extract_function_source(script_path, "matrix_multiply")
        assert fn_source == canonical_fn, (
            f"matrix_multiply mismatch in {script_rel}"
        )


def test_designed_quickstart_requires_completed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_module(EXAMPLES / "comparison" / "quickstart.py")
    created: list[ns.Job] = []

    class _FakeQuickRun:
        def __init__(self, status: str) -> None:
            self.id = "job-quick-1"
            self.status = status

        def wait(self) -> dict[str, object]:
            return {"status": {"state": self.status}}

    state = {"value": "COMPLETED"}

    def fake_create(self: ns.Job) -> _FakeQuickRun:
        created.append(self)
        return _FakeQuickRun(state["value"])

    monkeypatch.setattr(module.ns.Job, "create", fake_create)
    module.main()
    assert len(created) == 1
    assert created[0].command == ("nvidia-smi",)
    assert created[0].gpu == "h100"
    assert created[0].timeout_seconds == 3600
    assert capsys.readouterr().out.strip() == "job-quick-1"

    state["value"] = "FAILED"
    with pytest.raises(RuntimeError, match="job-quick-1: FAILED"):
        module.main()


class _FakeClock:
    def __init__(self) -> None:
        self.now = 500.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds
        if len(self.sleeps) > 40:
            raise AssertionError("unbounded sleep in report retrieval")


class _FakeBatchRun:
    def __init__(
        self,
        job_id: str,
        final_status: str,
        events: list[tuple[object, ...]],
        size: int,
    ) -> None:
        self.id = job_id
        self.status: str | None = None
        self._final_status = final_status
        self._events = events
        self._size = size

    def wait(self, timeout: float | None = None) -> dict[str, object]:
        self._events.append(("wait", self._size, self.id, timeout))
        self.status = self._final_status
        return {"status": {"state": self._final_status}}


def _valid_report(size: int) -> dict[str, object]:
    return {
        "schema_version": 1,
        "size": size,
        "gpu": "NVIDIA H100 80GB HBM3",
        "elapsed_ms": float(size) / 10.0,
        "mean": 0.00125,
        "verified": True,
    }


def _patch_batch(
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
    *,
    status_for: Callable[[int], str] | None = None,
    stdout_for: Callable[[int], str] | None = None,
    on_aws: Callable[[Sequence[str]], None] | None = None,
    clock: _FakeClock | None = None,
) -> tuple[list[tuple[object, ...]], list[ns.Job]]:
    events: list[tuple[object, ...]] = []
    jobs: list[ns.Job] = []

    def create(
        self: ns.Job, *_args: object, **_kwargs: object
    ) -> _FakeBatchRun:
        size = int(self.command[-1])
        events.append(("create", size))
        jobs.append(self)
        final_status = (
            "COMPLETED" if status_for is None else status_for(size)
        )
        return _FakeBatchRun(f"job-{size}", final_status, events, size)

    def run_aws(
        args: Sequence[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        cmd = tuple(args)
        events.append(("aws", cmd, kwargs.get("timeout")))
        if on_aws is not None:
            on_aws(cmd)
        uri = str(cmd[3])
        size = int(uri.rsplit("/", 1)[-1].removesuffix(".json"))
        body = (
            json.dumps(_valid_report(size))
            if stdout_for is None
            else stdout_for(size)
        )
        return subprocess.CompletedProcess(
            list(args), 0, stdout=body, stderr=""
        )

    monkeypatch.setattr(module.ns.Job, "create", create)
    monkeypatch.setattr(module.subprocess, "run", run_aws)
    if clock is not None:
        monkeypatch.setattr(module.time, "monotonic", clock.monotonic)
        monkeypatch.setattr(module.time, "sleep", clock.sleep)
    return events, jobs


def test_batch_matrix_multiply_offline_behavior(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        subprocess, "run", lambda *_a, **_kw: calls.append("subprocess")
    )
    monkeypatch.setattr(
        ns.Job, "create", lambda *_a, **_kw: calls.append("create")
    )
    module = _load_module(EXAMPLES / "batch" / "matrix_multiply.py")
    assert calls == []
    assert "torch" not in sys.modules

    events, jobs = _patch_batch(monkeypatch, module)
    module.main()
    out = capsys.readouterr().out

    assert [e[0] for e in events[:3]] == ["create", "create", "create"]
    assert [e[1] for e in events[:3]] == [1024, 2048, 4096]
    first_prefix = jobs[0].command[3]
    assert first_prefix.startswith("matrix-multiply/")
    for size, job in zip((1024, 2048, 4096), jobs, strict=True):
        assert job.gpu == "h100"
        assert job.timeout_seconds == 3600
        assert job.volumes == ("s3://acceptance-bucket:/data:rw",)
        assert job.command == (
            "python",
            "-c",
            module.WORKER,
            first_prefix,
            str(size),
        )
        assert f"{size}\tNVIDIA H100 80GB HBM3" in out

    module.main()
    second_prefix = jobs[3].command[3]
    assert second_prefix != first_prefix

    for bad_payload in (
        {**_valid_report(1024), "schema_version": True},
        {**_valid_report(1024), "size": 2048},
        {**_valid_report(1024), "size": True},
        {**_valid_report(1024), "elapsed_ms": True},
        {**_valid_report(1024), "elapsed_ms": float("inf")},
        {**_valid_report(1024), "mean": False},
        {**_valid_report(1024), "mean": float("nan")},
        {**_valid_report(1024), "verified": False},
    ):
        with pytest.raises(ValueError):
            module.validate_report(bad_payload, 1024)

    events_fail, _ = _patch_batch(
        monkeypatch,
        module,
        status_for=lambda sz: "FAILED" if sz == 1024 else "COMPLETED",
    )
    with pytest.raises(SystemExit, match="job-1024 ended FAILED"):
        module.main()
    assert not any(e[0] == "aws" for e in events_fail)

    clock = _FakeClock()

    def always_404(_cmd: Sequence[str]) -> None:
        raise subprocess.CalledProcessError(
            1, ["aws"], stderr="404 NoSuchKey"
        )

    events_404, _ = _patch_batch(
        monkeypatch, module, on_aws=always_404, clock=clock
    )
    with pytest.raises(SystemExit, match="report missing"):
        module.main()
    aws_tries = [e for e in events_404 if e[0] == "aws"]
    assert len(aws_tries) == module.REPORT_SECONDS // module.REPORT_PAUSE

    clock_403 = _FakeClock()

    def fail_403(_cmd: Sequence[str]) -> None:
        raise subprocess.CalledProcessError(
            1, ["aws"], stderr="403 AccessDenied"
        )

    events_403, _ = _patch_batch(
        monkeypatch, module, on_aws=fail_403, clock=clock_403
    )
    with pytest.raises(SystemExit, match="cannot retrieve"):
        module.main()
    assert len([e for e in events_403 if e[0] == "aws"]) == 1
    assert clock_403.sleeps == []

    clock_nan = _FakeClock()
    events_nan, _ = _patch_batch(
        monkeypatch,
        module,
        stdout_for=lambda _sz: '{"schema_version": 1, "elapsed_ms": NaN}',
        clock=clock_nan,
    )
    with pytest.raises(SystemExit, match="malformed report"):
        module.main()
    assert len([e for e in events_nan if e[0] == "aws"]) == 1
    assert clock_nan.sleeps == []


def test_measurements_reconcile_and_match_sdk_comparison_doc() -> None:
    measure = _load_module(EXAMPLES / "comparison" / "measure.py")
    variants, reductions = measure.measure_all()
    assert len(variants) == 10
    assert len(reductions) == 2

    for item in variants:
        assert item.orchestration + item.workload_and_data == item.python_total
        for fc in item.files:
            assert fc.orchestration + fc.workload_and_data == fc.python_total

    by_key = {(item.task, item.variant): item for item in variants}
    assert (
        by_key[("Quickstart", "Official Nebius SDK")].workload_and_data
        == by_key[("Quickstart", "Designed Nebius SDK")].workload_and_data
    )
    assert (
        by_key[("Batch (3 sizes)", "Official Nebius SDK")].workload_and_data
        == by_key[("Batch (3 sizes)", "Designed Nebius SDK")].workload_and_data
    )

    doc_text = (ROOT / "docs" / "sdk-comparison.md").read_text(
        encoding="utf-8"
    )
    for panel_num in range(1, 7):
        assert f"## Panel {panel_num}:" in doc_text

    for item in variants:
        label = f"| {item.task} — {item.variant} | {item.python_total} | "
        label += f"{item.orchestration} | {item.workload_and_data} |"
        assert label in doc_text, f"Missing row in docs: {label}"
        for fc in item.files:
            assert fc.sha256 in doc_text, (
                f"Missing SHA-256 for {fc.relpath} in docs/sdk-comparison.md"
            )
        for npc in item.non_python_files:
            assert npc.sha256 in doc_text, (
                f"Missing SHA-256 for {npc.relpath} in docs/sdk-comparison.md"
            )

    for red in reductions:
        assert f"{red.orchestration_reduction_pct:.1f}%" in doc_text
        assert f"{red.total_reduction_pct:.1f}%" in doc_text

    completed = subprocess.run(
        [
            sys.executable,
            str(EXAMPLES / "comparison" / "measure.py"),
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)
    assert len(payload["variants"]) == 10
    assert len(payload["reductions"]) == 2
