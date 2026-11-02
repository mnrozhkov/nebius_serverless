"""Offline tests for the SDK comparison suite and measurement runner."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from importlib.machinery import ModuleSpec
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

import pytest

import nebius_serverless as ns

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
COMPARISON_FILES = (
    EXAMPLES / "job_quickstart.py",
    EXAMPLES / "train" / "axolotl_lora.py",
    EXAMPLES / "benchmark" / "measure.py",
    EXAMPLES / "benchmark" / "nebius" / "quickstart.py",
    EXAMPLES / "benchmark" / "nebius" / "axolotl_lora.py",
    EXAMPLES / "benchmark" / "modal" / "quickstart.py",
    EXAMPLES / "benchmark" / "modal" / "axolotl_lora.py",
    EXAMPLES / "benchmark" / "runpod" / "quickstart.py",
    EXAMPLES / "benchmark" / "runpod" / "axolotl_lora.py",
)


def _load_module(path: Path) -> ModuleType:
    spec: ModuleSpec | None = spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_all_comparison_python_files_parse_without_importing_competitors() -> (
    None
):
    benchmark_files = sorted(
        path
        for path in (EXAMPLES / "benchmark").rglob("*.py")
        if ".venv" not in path.parts
    )
    assert benchmark_files == sorted(
        path for path in COMPARISON_FILES if "benchmark" in path.parts
    )

    for path in COMPARISON_FILES:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        assert isinstance(tree, ast.Module)

    assert "modal" not in sys.modules
    assert "runpod" not in sys.modules


def test_designed_quickstart_creates_and_waits(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_module(EXAMPLES / "job_quickstart.py")
    created: list[ns.Job] = []

    class _FakeQuickRun:
        def __init__(self) -> None:
            self.id = "job-quick-1"
            self.status = "COMPLETED"
            self.record = {"status": {"state": "COMPLETED"}}

        def wait(self) -> dict[str, object]:
            return self.record

        def display(self) -> None:
            print(f"{self.id}\n  {self.status}")

    def fake_create(self: ns.Job) -> _FakeQuickRun:
        created.append(self)
        return _FakeQuickRun()

    monkeypatch.setattr(module.ns.Job, "create", fake_create)
    module.main()
    assert len(created) == 1
    assert created[0].command == ("nvidia-smi",)
    assert created[0].gpu == "h100"
    assert created[0].timeout_seconds == 3600
    out = capsys.readouterr().out
    assert "job-quick-1" in out
    assert "COMPLETED" in out


def test_designed_axolotl_lora_creates_and_waits(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_module(EXAMPLES / "train" / "axolotl_lora.py")
    created: list[ns.Job] = []

    class _FakeTrainRun:
        def __init__(self) -> None:
            self.id = "job-train-1"
            self.status = "COMPLETED"
            self.record = {"status": {"state": "COMPLETED"}}

        def wait(self) -> dict[str, object]:
            return self.record

        def display(self) -> None:
            print(f"{self.id}\n  {self.status}")

    def fake_create(self: ns.Job) -> _FakeTrainRun:
        created.append(self)
        return _FakeTrainRun()

    monkeypatch.setattr(module.ns.Job, "create", fake_create)
    module.main()
    assert len(created) == 1
    job = created[0]
    assert job.command == (
        "bash",
        "-lc",
        "axolotl train /workspace/data/config.yaml",
    )
    assert (
        job.image
        == "docker.io/axolotlai/axolotl:main-20260309-py3.11-cu128-2.9.1"
    )
    assert job.gpu == "h100"
    assert job.pricing == "spot"
    assert job.disk == "500Gi"
    assert job.timeout_seconds == 24 * 3600
    assert job.volumes == (
        "s3://axolotl-data:/workspace/data:ro",
        "s3://axolotl-artifacts:/workspace/artifacts:rw",
    )
    out = capsys.readouterr().out
    assert "job-train-1" in out
    assert "COMPLETED" in out


def test_official_axolotl_lora_builds_matching_create_request(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_module(
        EXAMPLES / "benchmark" / "nebius" / "axolotl_lora.py"
    )
    captured_requests: list[object] = []
    closed: list[bool] = []

    class _FakeConfig:
        parent_id = "project-test-1"

    class _FakeSDK:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def sync_close(self) -> None:
            closed.append(True)

    class _FakeOperation:
        resource_id = "aijob-test-axolotl"

        def sync_wait(self) -> None:
            pass

    class _FakeOpCall:
        def wait(self) -> _FakeOperation:
            return _FakeOperation()

    class _FakeState:
        name = "COMPLETED"

    class _FakeStatus:
        state = _FakeState()

    class _FakeJobResponse:
        status = _FakeStatus()

    class _FakeGetCall:
        def wait(self) -> _FakeJobResponse:
            return _FakeJobResponse()

    class _FakeClient:
        def __init__(self, _sdk: object) -> None:
            pass

        def create(self, request: object) -> _FakeOpCall:
            captured_requests.append(request)
            return _FakeOpCall()

        def get(self, _request: object) -> _FakeGetCall:
            return _FakeGetCall()

    monkeypatch.setattr(module, "Config", _FakeConfig)
    monkeypatch.setattr(module, "SDK", _FakeSDK)
    monkeypatch.setattr(module, "JobServiceClient", _FakeClient)

    module.main()
    assert len(captured_requests) == 1
    assert closed == [True]
    assert "aijob-test-axolotl" in capsys.readouterr().out

    req = captured_requests[0]
    spec = getattr(req, "spec")
    assert (
        spec.image
        == "docker.io/axolotlai/axolotl:main-20260309-py3.11-cu128-2.9.1"
    )
    assert spec.container_command == "bash"
    assert spec.args == "-lc 'axolotl train /workspace/data/config.yaml'"
    assert spec.platform == "gpu-h100-sxm"
    assert spec.preset == "1gpu-16vcpu-200gb"
    assert spec.preemptible is True
    assert spec.shm_size_bytes == 16 * 1024**3
    assert spec.disk.size_bytes == 500 * 1024**3
    assert len(spec.volumes) == 2
    assert spec.volumes[0].source == "s3://axolotl-data"
    assert spec.volumes[0].container_path == "/workspace/data"
    assert spec.volumes[1].source == "s3://axolotl-artifacts"
    assert spec.volumes[1].container_path == "/workspace/artifacts"


def test_measurements_reconcile_and_match_sdk_comparison_doc() -> None:
    measure = _load_module(EXAMPLES / "benchmark" / "measure.py")
    variants, reductions = measure.measure_all()
    assert len(variants) == 8
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
        by_key[
            ("Fine-tuning (Axolotl)", "Official Nebius SDK")
        ].workload_and_data
        == by_key[
            ("Fine-tuning (Axolotl)", "Designed Nebius SDK")
        ].workload_and_data
    )

    doc_text = (EXAMPLES / "benchmark" / "sdk-comparison.md").read_text(
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
                f"Missing SHA-256 for {fc.relpath} in "
                "examples/benchmark/sdk-comparison.md"
            )

    for red in reductions:
        assert f"{red.orchestration_reduction_pct:.1f}%" in doc_text
        assert f"{red.total_reduction_pct:.1f}%" in doc_text

    completed = subprocess.run(
        [
            sys.executable,
            str(EXAMPLES / "benchmark" / "measure.py"),
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)
    assert len(payload["variants"]) == 8
    assert len(payload["reductions"]) == 2
