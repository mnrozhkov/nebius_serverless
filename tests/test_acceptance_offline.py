"""Offline dry-runs of the three acceptance scripts."""

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
ACCEPTANCE = ROOT / "examples" / "acceptance"
CUDA = "nvidia/cuda:13.1.1-runtime-ubuntu24.04"
AXOLOTL = "docker.io/axolotlai/axolotl:main-20260309-py3.11-cu128-2.9.1"


def _load(name: str) -> object:
    sys.path.insert(0, str(ACCEPTANCE))
    return _load_path(ACCEPTANCE / f"{name}.py")


def _load_path(path: Path) -> object:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def load(
        profile: str | None = None,
        **kwargs: object,
    ) -> tuple[str, str]:
        return ("project-1", "eu-north1")

    monkeypatch.setattr("nebius_serverless.job.load_profile", load)


def _printed(capsys: pytest.CaptureFixture[str]) -> list[dict[str, object]]:
    lines = [
        line
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("{")
    ]
    return [ast.literal_eval(line) for line in lines]


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
    lowered = text.lower()
    assert "local backend" not in lowered
    assert "live nebius run" not in lowered


def test_examples_pass_gpu_aliases() -> None:
    for path in (ROOT / "examples").rglob("*"):
        if path.suffix not in {".py", ".yaml"}:
            continue
        text = path.read_text(encoding="utf-8")
        assert "platform=" not in text
        assert "preset=" not in text
        assert "\nplatform:" not in text
        assert "\npreset:" not in text


def test_quickstart_dry_run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _profile(monkeypatch)
    module = _load_path(ROOT / "examples" / "quickstart.py")
    monkeypatch.setattr(sys, "argv", ["quickstart.py"])
    module.main()
    printed = _printed(capsys)
    assert len(printed) == 1
    request = printed[0]
    assert request["image"] == CUDA
    assert request["command"] == ["nvidia-smi"]
    assert "args" not in request
    assert request["platform"] == "gpu-h100-sxm"
    assert request["preset"] == "1gpu-16vcpu-200gb"
    assert request["timeout"] == 3600
    assert request["pricing"] == "on-demand"


def test_short_job_yaml_matches_the_constructor(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _profile(monkeypatch)
    module = _load("nvidia_smi")
    monkeypatch.setattr(sys, "argv", ["nvidia_smi.py"])
    module.main()
    printed = _printed(capsys)
    assert len(printed) == 2
    assert printed[0] == printed[1]
    request = printed[0]
    assert request["image"] == CUDA
    assert request["command"] == ["bash", "-c", "nvidia-smi"]
    assert request["args"] == "-c nvidia-smi"
    assert request["platform"] == "gpu-l40s-a"
    assert request["preset"] == "1gpu-8vcpu-32gb"
    assert request["timeout"] == 3600
    assert request["name"] == "my-job"
    assert request["pricing"] == "on-demand"
    assert request["disk"] == "250Gi"
    assert request["shm"] == "16Gi"


def test_axolotl_dry_run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _profile(monkeypatch)
    module = _load("axolotl_lora")
    monkeypatch.setattr(sys, "argv", ["axolotl_lora.py"])
    module.main()
    printed = _printed(capsys)
    assert len(printed) == 1
    request = printed[0]
    assert request["image"] == AXOLOTL
    assert request["platform"] == "gpu-h100-sxm"
    assert request["preset"] == "1gpu-16vcpu-200gb"
    assert request["pricing"] == "spot"
    assert request["disk"] == "500Gi"
    assert request["timeout"] == 24 * 3600
    assert request["shm"] == "16Gi"
    assert "volumes" not in request


def test_line_count_dry_run_does_not_upload(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _profile(monkeypatch)
    monkeypatch.delenv("ACCEPTANCE_BUCKET", raising=False)
    module = _load("line_count")
    monkeypatch.setattr(sys, "argv", ["line_count.py"])
    module.main()
    printed = _printed(capsys)
    assert len(printed) == 3
    for request in printed:
        assert request["image"] == "python:3.12-slim"
        assert request["platform"] == "gpu-h100-sxm"
        assert request["timeout"] == 3600
        assert "volumes" not in request
    monkeypatch.setenv("ACCEPTANCE_BUCKET", "bucket")
    module.main()
    with_bucket = _printed(capsys)
    assert len(with_bucket) == 3
    for request in with_bucket:
        assert request["volumes"] == ["s3://bucket:/data:rw"]
