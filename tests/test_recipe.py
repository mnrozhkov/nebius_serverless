"""Recipe validation, aliases, YAML, and dry-run descriptions."""

import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest

import nebius_serverless as ns

IMAGE = "python:3.12-slim"
CUDA = "nvidia/cuda:13.1.1-runtime-ubuntu24.04"
DIGEST = "registry/path@sha256:" + ("ab" * 32)
SECRET = "super-secret-value"


def _job(**kwargs: object) -> ns.Job:
    fields: dict[str, object] = {
        "image": IMAGE,
        "timeout": "1h",
    }
    fields.update(kwargs)
    command = fields.pop("command", ["nvidia-smi"])
    return ns.Job(command, **fields)  # type: ignore[arg-type]


def _dry(job: ns.Job, region: str = "eu-north1") -> dict[str, object]:
    described = job.create(
        dry_run=True,
        region=region,
        project="project-1",
    )
    assert isinstance(described, dict)
    return described


def test_h100_dry_run_in_eu_north1() -> None:
    described = _dry(
        _job(
            command=["nvidia-smi"],
            image=CUDA,
            gpu="h100",
        )
    )
    assert described["image"] == CUDA
    assert described["platform"] == "gpu-h100-sxm"
    assert described["preset"] == "1gpu-16vcpu-200gb"
    assert described["timeout"] == 3600
    assert described["pricing"] == "on-demand"
    assert described["command"] == ["nvidia-smi"]
    assert "args" not in described
    assert described["disk"] == "250Gi"
    assert described["shm"] == "16Gi"
    assert described["project"] == "project-1"
    assert described["region"] == "eu-north1"
    assert SECRET not in str(described)


@pytest.mark.parametrize(
    ("gpu", "region", "platform"),
    [
        ("b200", "me-west1", "gpu-b200-sxm-a"),
        ("b200", "us-central1", "gpu-b200-sxm"),
        ("rtx", "us-central1", "gpu-rtx6000"),
        ("rtx", "eu-south1", "gpu-rtx6000-a"),
        ("rtx", "uk-south2", "gpu-rtx6000-a"),
        ("h200", "eu-west1", "gpu-h200-sxm"),
        ("l40s", "eu-north1", "gpu-l40s-a"),
    ],
)
def test_alias_rows(gpu: str, region: str, platform: str) -> None:
    described = _dry(_job(gpu=gpu), region)
    assert described["platform"] == platform


def test_h100_is_absent_from_us_central1() -> None:
    job = _job(gpu="h100")
    with pytest.raises(ns.ValidationError, match="eu-north1"):
        job.create(
            dry_run=True,
            region="us-central1",
            project="project-1",
        )


def test_omitted_gpu_is_cpu_and_cpu_string_is_rejected() -> None:
    described = _dry(_job(), "us-central1")
    assert described["platform"] == "cpu-d3"
    assert described["preset"] == "2vcpu-8gb"
    with pytest.raises(ns.ValidationError, match="[Oo]mit gpu"):
        _job(gpu="cpu")


def test_platform_overrides_gpu_and_unknown_platform_needs_preset() -> None:
    described = _dry(
        _job(gpu="h100", platform="gpu-l40s-a"),
        "us-central1",
    )
    assert described["platform"] == "gpu-l40s-a"
    assert described["preset"] == "1gpu-8vcpu-32gb"
    known = _dry(_job(platform="gpu-h100-sxm"))
    assert known["preset"] == "1gpu-16vcpu-200gb"
    with pytest.raises(ns.ValidationError, match="preset"):
        _job(platform="gpu-custom")
    custom = _dry(
        _job(platform="gpu-custom", preset="my-preset"),
        "us-central1",
    )
    assert custom["platform"] == "gpu-custom"
    assert custom["preset"] == "my-preset"


@pytest.mark.parametrize(
    "timeout",
    ["1h", 3600, 3600.0, timedelta(hours=1), "168h", timedelta(hours=168)],
)
def test_timeout_bounds_accept_one_hour_and_the_maximum(
    timeout: object,
) -> None:
    described = _dry(_job(timeout=timeout))
    assert described["timeout"] in (3600, 168 * 3600)


@pytest.mark.parametrize(
    "timeout",
    [3599, timedelta(hours=1) - timedelta(seconds=1), "169h", 604801],
)
def test_timeout_bounds_reject_without_clamping(timeout: object) -> None:
    with pytest.raises(ns.ValidationError, match="168"):
        _job(timeout=timeout)


def test_images_commands_and_quoting() -> None:
    tagged = _dry(_job(image=CUDA))
    digested = _dry(_job(image=DIGEST))
    assert tagged["image"] == CUDA
    assert digested["image"] == DIGEST
    with pytest.raises(ns.ValidationError, match="shell string"):
        _job(command="nvidia-smi")
    quoted = _dry(_job(command=["echo", "hello world"]))
    assert quoted["args"] == "'hello world'"
    assert "args" not in _dry(_job(command=["nvidia-smi"]))


def test_pricing_spot_on_cpu_and_unknown_price() -> None:
    with pytest.raises(ns.UnsupportedFeature):
        _job(pricing="spot")
    with pytest.raises(ns.ValidationError):
        _job(pricing="preemptible")
    described = _dry(_job(gpu="h100", pricing="spot"))
    assert described["pricing"] == "spot"


def test_disk_name_subnet_volumes_and_env_keys() -> None:
    described = _dry(
        _job(
            disk="500Gi",
            subnet_id="subnet-1",
            volumes=["s3://bucket:/data:rw"],
            env={"TOKEN": SECRET, "A": "1"},
            name="my-job",
        )
    )
    assert described["disk"] == "500Gi"
    assert described["shm"] == "16Gi"
    assert described["subnet_id"] == "subnet-1"
    assert described["volumes"] == ["s3://bucket:/data:rw"]
    assert described["env"] == ["TOKEN", "A"]
    assert described["name"] == "my-job"
    assert SECRET not in str(described)
    generated = _dry(_job())
    again = _dry(_job())
    assert generated["name"] != again["name"]
    assert str(generated["name"]).startswith("job-")
    stable = _job()
    assert _dry(stable)["name"] == _dry(stable)["name"]
    relative = _dry(_job(command=["./tool", "arg"]))
    assert relative["command"] == ["./tool", "arg"]


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "job.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_from_yaml_matches_the_constructor(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "\n".join(
            [
                "schema_version: 1",
                "kind: job",
                f"image: {CUDA}",
                'command: ["bash", "-c", "nvidia-smi"]',
                "platform: gpu-l40s-a",
                "preset: 1gpu-8vcpu-32gb",
                "timeout: 1h",
                "name: my-job",
                "env:",
                f"  TOKEN: {SECRET}",
            ]
        )
        + "\n",
    )
    loaded = ns.Job.from_yaml(path)
    built = ns.Job(
        ["bash", "-c", "nvidia-smi"],
        image=CUDA,
        platform="gpu-l40s-a",
        preset="1gpu-8vcpu-32gb",
        timeout="1h",
        name="my-job",
        env={"TOKEN": SECRET},
    )
    assert _dry(loaded) == _dry(built)
    assert SECRET not in str(_dry(loaded))


def test_function_yaml_and_rejected_documents(tmp_path: Path) -> None:
    function = _write(
        tmp_path,
        "schema_version: 1\nkind: function\nimage: python:3.12-slim\n"
        "command: [nvidia-smi]\ntimeout: 1h\n",
    )
    with pytest.raises(ns.ValidationError):
        ns.Job.from_yaml(function)
    unknown = _write(
        tmp_path,
        "schema_version: 1\nkind: job\nimage: python:3.12-slim\n"
        "command: [nvidia-smi]\ntimeout: 1h\nextra: 1\n",
    )
    with pytest.raises(ns.ValidationError, match="Unknown YAML keys"):
        ns.Job.from_yaml(unknown)
    cpu = _write(
        tmp_path,
        "schema_version: 1\nkind: job\nimage: python:3.12-slim\n"
        "command: [nvidia-smi]\ntimeout: 1h\ngpu: cpu\n",
    )
    with pytest.raises(ns.ValidationError, match="[Oo]mit gpu"):
        ns.Job.from_yaml(cpu)
    shell = _write(
        tmp_path,
        "schema_version: 1\nkind: job\nimage: python:3.12-slim\n"
        "command: nvidia-smi\ntimeout: 1h\n",
    )
    with pytest.raises(ns.ValidationError, match="shell string"):
        ns.Job.from_yaml(shell)


@pytest.mark.parametrize(
    ("text", "match"),
    [
        (
            "schema_version: 1\nschema_version: 1\nkind: job\n",
            "Duplicate",
        ),
        (
            "schema_version: &a 1\nkind: job\n",
            "anchor",
        ),
            (
                "*a\n",
                "alias",
            ),
        (
            "schema_version: !!str 1\nkind: job\n",
            "tag",
        ),
        (
            "<<: {image: python:3.12-slim}\nkind: job\n",
            "merge",
        ),
    ],
)
def test_yaml_constructs_are_rejected(
    tmp_path: Path,
    text: str,
    match: str,
) -> None:
    with pytest.raises(ns.ValidationError, match=match):
        ns.Job.from_yaml(_write(tmp_path, text))


def test_yaml_over_one_mebibyte_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "big.yaml"
    path.write_bytes(b"a" * (1024 * 1024 + 1))
    with pytest.raises(ns.ValidationError, match="1 MiB"):
        ns.Job.from_yaml(path)


def test_construct_and_yaml_do_not_import_the_sdk(tmp_path: Path) -> None:
    document = _write(
        tmp_path,
        "schema_version: 1\nkind: job\nimage: python:3.12-slim\n"
        "command: [nvidia-smi]\ntimeout: 1h\n",
    )
    code = (
        "import sys\n"
        "import nebius_serverless as ns\n"
        "ns.Job(['nvidia-smi'], image='python:3.12-slim', timeout='1h')\n"
        "job = ns.Job.from_yaml(sys.argv[1])\n"
        "job.create(dry_run=True, region='eu-north1', project='p')\n"
        "assert 'nebius' not in sys.modules\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code, str(document)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
