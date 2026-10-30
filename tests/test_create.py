"""Create mapping, lost ids, and profile resolution."""

from pathlib import Path

import pytest
from fakes import FakeTransport

import nebius_serverless as ns

CUDA = "nvidia/cuda:13.1.1-runtime-ubuntu24.04"
SECRET = "super-secret-value"


def _job(**kwargs: object) -> ns.Job:
    fields: dict[str, object] = {
        "image": CUDA,
        "gpu": "h100",
        "timeout": "1h",
        "env": {"TOKEN": SECRET},
    }
    fields.update(kwargs)
    command = fields.pop("command", ["nvidia-smi"])
    return ns.Job(command, **fields)  # type: ignore[arg-type]


def _spec(body: dict[str, object]) -> dict[str, object]:
    spec = body["spec"]
    assert isinstance(spec, dict)
    return spec


def test_nvidia_smi_body_and_a_second_create() -> None:
    fake = FakeTransport()
    job = _job(name="my-job", command=["bash", "-c", "echo hello world"])
    run = job.create(
        region="eu-north1",
        project="project-1",
        transport=fake,
    )
    assert isinstance(run, ns.Run)
    assert run.id == "job-1"
    assert run.name == "my-job"
    assert run.status == "PROVISIONING"
    assert run.record is None
    spec = _spec(fake.bodies[0])
    assert spec["image"] == CUDA
    assert spec["container_command"] == "bash"
    assert spec["args"] == "-c 'echo hello world'"
    assert spec["platform"] == "gpu-h100-sxm"
    assert spec["preset"] == "1gpu-16vcpu-200gb"
    assert spec["timeout_seconds"] == 3600
    assert spec["disk"] == "250Gi"
    assert spec["shm_size_bytes"] == 16 * 1024**3
    assert "preemptible" not in spec
    assert "follows_spot_price" not in spec
    metadata = fake.bodies[0]["metadata"]
    assert metadata == {"parent_id": "project-1", "name": "my-job"}
    second = job.create(
        region="eu-north1",
        project="project-1",
        transport=fake,
    )
    assert isinstance(second, ns.Run)
    assert second.id == "job-2"
    assert len(fake.bodies) == 2


def test_spot_flags_and_dry_run_skips_create() -> None:
    fake = FakeTransport()
    job = _job(pricing="spot", disk="500Gi", volumes=["data:/work:ro"])
    described = job.create(
        dry_run=True,
        region="eu-north1",
        project="project-1",
        transport=fake,
    )
    assert isinstance(described, dict)
    assert described["pricing"] == "spot"
    assert described["disk"] == "500Gi"
    assert described["env"] == ["TOKEN"]
    assert SECRET not in str(described)
    assert fake.bodies == []
    job.create(
        region="eu-north1",
        project="project-1",
        transport=fake,
    )
    spec = _spec(fake.bodies[0])
    assert spec["preemptible"] is True
    assert spec["follows_spot_price"] is True
    assert "pricing_policy" not in str(spec)
    assert spec["disk"] == "500Gi"
    variables = spec["environment_variables"]
    assert variables == [{"name": "TOKEN", "value": SECRET}]
    assert spec["volumes"] == [
        {"source": "data", "container_path": "/work", "mode": "ro"}
    ]


def test_lost_id_and_transport_failure_do_not_retry() -> None:
    lost = FakeTransport()
    lost.drop_id = True
    job = _job()
    with pytest.raises(ns.SubmissionUncertain):
        job.create(
            region="eu-north1",
            project="project-1",
            transport=lost,
        )
    assert len(lost.bodies) == 1
    failed = FakeTransport()
    failed.failure = "transport"
    with pytest.raises(ns.TransportError) as caught:
        job.create(
            region="eu-north1",
            project="project-1",
            transport=failed,
        )
    assert len(failed.bodies) == 1
    assert SECRET not in str(caught.value)


@pytest.mark.parametrize(
    ("failure", "error", "conflict_id"),
    [
        ("access", ns.AccessError, None),
        ("capacity", ns.CapacityError, None),
        ("conflict", ns.KeyConflict, "job-existing"),
        ("conflict", ns.SubmissionUncertain, None),
        ("uncertain", ns.SubmissionUncertain, None),
    ],
)
def test_create_errors_hide_env_values(
    failure: str,
    error: type[Exception],
    conflict_id: str | None,
) -> None:
    fake = FakeTransport()
    fake.failure = failure
    fake.conflict_id = conflict_id
    with pytest.raises(error) as caught:
        _job().create(
            region="eu-north1",
            project="project-1",
            transport=fake,
        )
    assert SECRET not in str(caught.value)
    if conflict_id is not None:
        assert caught.value.run_id == conflict_id
    assert len(fake.bodies) == 1


def test_explicit_location_skips_the_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(profile: str | None = None, **kwargs: object) -> tuple[str, str]:
        raise AssertionError(profile)

    monkeypatch.setattr("nebius_serverless.job.load_profile", boom)
    described = _job().create(
        dry_run=True,
        region="eu-north1",
        project="project-1",
    )
    assert isinstance(described, dict)
    assert described["region"] == "eu-north1"


def test_missing_profile_fails_before_create(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(
        profile: str | None = None,
        **kwargs: object,
    ) -> tuple[str, str]:
        raise ns.ValidationError("missing", operation="create")

    monkeypatch.setattr("nebius_serverless.job.load_profile", missing)
    fake = FakeTransport()
    with pytest.raises(ns.ValidationError):
        _job().create(transport=fake)
    assert fake.bodies == []


def test_profile_file_supplies_project_and_region(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "\n".join(
            [
                "default: test",
                "profiles:",
                "  test:",
                "    parent-id: project-123",
                "    endpoint: api.eu-north1.nebius.cloud",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    from nebius_serverless.profile import load_profile

    assert load_profile(config_file=path) == ("project-123", "eu-north1")
    empty = tmp_path / "empty.yaml"
    empty.write_text(
        "default: test\nprofiles:\n  test:\n    endpoint: api.nebius.cloud\n",
        encoding="utf-8",
    )
    with pytest.raises(ns.ValidationError):
        load_profile(config_file=empty)
    ambiguous = tmp_path / "ambiguous.yaml"
    ambiguous.write_text(
        "profiles:\n  a:\n    parent-id: p1\n  b:\n    parent-id: p2\n",
        encoding="utf-8",
    )
    with pytest.raises(ns.ValidationError):
        load_profile(config_file=ambiguous)


def test_sdk_request_omits_on_demand_flags() -> None:
    from nebius_serverless.recipe import request_body
    from nebius_serverless.sdk_transport import (
        build_create_request,
        classify_code,
    )

    body = request_body(
        command=["nvidia-smi"],
        image=CUDA,
        project="project-1",
        platform="gpu-h100-sxm",
        preset="1gpu-16vcpu-200gb",
        timeout=3600,
        pricing="on-demand",
        subnet_id=None,
        volumes=(),
        env=(("TOKEN", SECRET),),
        name="my-job",
        disk=None,
    )
    request = build_create_request(body)
    payload = request.to_json(preserving_proto_field_name=True)
    assert "preemptible" not in payload
    assert "followsSpotPrice" not in payload
    assert "follows_spot_price" not in payload
    assert "250" in payload or "268435456000" in payload
    assert SECRET in payload
    spot = request_body(
        command=["nvidia-smi"],
        image=CUDA,
        project="project-1",
        platform="gpu-h100-sxm",
        preset="1gpu-16vcpu-200gb",
        timeout=3600,
        pricing="spot",
        subnet_id=None,
        volumes=(),
        env=(),
        name="my-job",
        disk="500Gi",
    )
    spot_request = build_create_request(spot)
    spot_payload = spot_request.to_json(preserving_proto_field_name=True)
    assert "follows_spot_price" in spot_payload or "followsSpotPrice" in (
        spot_payload
    )
    assert "spot_pricing_policy" not in spot_payload
    assert "SpotPricingPolicy" not in spot_payload
    access = classify_code(
        "UNAUTHENTICATED",
        sent=False,
        conflict_id=None,
        capacity=False,
        access=False,
    )
    assert access.failure == "access"
    conflict = classify_code(
        "ALREADY_EXISTS",
        sent=True,
        conflict_id="job-existing",
        capacity=False,
        access=False,
    )
    assert conflict.failure == "conflict"
    assert conflict.conflict_id == "job-existing"
    lost = classify_code(
        "UNAVAILABLE",
        sent=True,
        conflict_id=None,
        capacity=False,
        access=False,
    )
    assert lost.failure == "uncertain"
