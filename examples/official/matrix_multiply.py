"""Three GPU matrix multiplications using the official Nebius SDK.

Each job multiplies two square matrices on CUDA and writes a JSON
report to a mounted Object Storage bucket. The script submits all three
jobs before waiting, polls each job until terminal, and validates the
retrieved JSON reports locally. An error stops the script; already
accepted jobs keep running.
"""

import json
import math

# --- orchestration: start ---
import shlex

# --- orchestration: end ---
import subprocess
import time

# --- orchestration: start ---
from datetime import timedelta

# --- orchestration: end ---
from uuid import uuid4

# --- orchestration: start ---
from nebius.aio.cli_config import Config
from nebius.api.nebius.ai.v1 import (
    CreateJobRequest,
    GetJobRequest,
    JobServiceClient,
    JobSpec,
)
from nebius.api.nebius.common.v1 import ResourceMetadata
from nebius.api.nebius.compute.v1 import DiskSpec as ComputeDisk
from nebius.sdk import SDK

WAIT_SECONDS = 5400
POLL_SECONDS = 1.0
TERMINAL_STATES = frozenset(
    {"COMPLETED", "FAILED", "CANCELLED", "ERROR"}
)
# --- orchestration: end ---

SIZES = (1024, 2048, 4096)
# Verified against the registry manifest for
# pytorch/pytorch:2.6.0-cuda12.6-cudnn9-runtime.
# PyTorch 2.6.0 (2.6.0+cu126), Python 3.11.11, CUDA 12.6.3, linux/amd64.
IMAGE = (
    "pytorch/pytorch"
    "@sha256:f894dae26e1ee8557c544f9cfdb9dc011b1552bf3c1e656b422f2e221d380e40"
)
BUCKET = "acceptance-bucket"
ENDPOINT = "https://storage.eu-north1.nebius.cloud"
REPORT_SECONDS = 60
REPORT_PAUSE = 2

_MISSING_MARKERS = ("404", "nosuchkey", "no such key")
_ACCESS_MARKERS = (
    "401",
    "403",
    "accessdenied",
    "access denied",
    "forbidden",
    "expiredtoken",
    "invalidaccesskeyid",
    "signaturedoesnotmatch",
    "unable to locate credentials",
    "invalidclienttokenid",
    "security token",
)
_COLUMNS = ("size", "gpu", "elapsed_ms", "mean", "verified")

WORKER = """
import json
import sys
from pathlib import Path


def matrix_multiply(size: int) -> dict[str, object]:
    \"\"\"Run and verify a CUDA float32 matrix multiplication.\"\"\"
    import statistics

    import torch

    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise ValueError(f"size must be a positive int, got {size!r}")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for matrix_multiply")

    torch.backends.cuda.matmul.allow_tf32 = False
    torch.set_float32_matmul_precision("highest")
    torch.manual_seed(42)
    torch.cuda.manual_seed_all(42)

    device = torch.device("cuda")
    with torch.no_grad():
        a = torch.randn((size, size), dtype=torch.float32, device=device)
        b = torch.randn((size, size), dtype=torch.float32, device=device)
        for _ in range(3):
            c = a @ b
        torch.cuda.synchronize()

        timings_ms: list[float] = []
        for _ in range(10):
            start = torch.cuda.Event(enable_timing=True)
            end = torch.cuda.Event(enable_timing=True)
            start.record()
            c = a @ b
            end.record()
            torch.cuda.synchronize()
            timings_ms.append(float(start.elapsed_time(end)))

        left = torch.tensor(
            [[1.0, 2.0], [3.0, 4.0]], dtype=torch.float32, device=device
        )
        right = torch.tensor(
            [[5.0, 6.0], [7.0, 8.0]], dtype=torch.float32, device=device
        )
        expected_2x2 = torch.tensor(
            [[19.0, 22.0], [43.0, 50.0]], dtype=torch.float32, device=device
        )
        if not torch.equal(left @ right, expected_2x2):
            raise RuntimeError("Deterministic 2x2 CUDA matmul check failed")

        if tuple(c.shape) != (size, size):
            raise RuntimeError(f"Unexpected result shape: {tuple(c.shape)}")
        if not bool(torch.isfinite(c).all().item()):
            raise RuntimeError(
                "Non-finite values in matrix multiplication result"
            )

        indices = [0, size // 2, size - 1]
        a_cpu = a.detach().cpu().to(torch.float64)
        b_cpu = b.detach().cpu().to(torch.float64)
        c_cpu = c.detach().cpu().to(torch.float64)
        for row in indices:
            for col in indices:
                ref = torch.dot(a_cpu[row, :], b_cpu[:, col])
                if not torch.isclose(
                    c_cpu[row, col], ref, rtol=1e-4, atol=1e-3
                ):
                    raise RuntimeError(
                        f"Sample check failed at ({row}, {col})"
                    )

        mean_val = float(c.mean().item())

    gpu_name = str(torch.cuda.get_device_name(0)).strip()
    if not gpu_name:
        raise RuntimeError("Empty CUDA device name")

    return {
        "schema_version": 1,
        "size": int(size),
        "gpu": gpu_name,
        "elapsed_ms": float(statistics.median(timings_ms)),
        "mean": mean_val,
        "verified": True,
    }


def main() -> None:
    \"\"\"Run one matrix size and write the validated summary to /data.\"\"\"
    prefix = sys.argv[1]
    size = int(sys.argv[2])
    summary = matrix_multiply(size)
    out_dir = Path("/data") / prefix
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{size}.json"
    payload = json.dumps(summary, allow_nan=False)
    with out_path.open("w", encoding="utf-8") as handle:
        handle.write(payload)


if __name__ == "__main__":
    main()
"""


def _require_sizes(sizes: tuple[int, ...]) -> None:
    """Reject a bad size list before any job is submitted."""
    seen: set[int] = set()
    for size in sizes:
        if (
            isinstance(size, bool)
            or not isinstance(size, int)
            or size <= 0
        ):
            raise SystemExit(
                f"size must be a positive integer, got {size!r}"
            )
        if size in seen:
            raise SystemExit(f"duplicate size {size}")
        seen.add(size)


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def _finite(value: object, name: str, *, positive: bool) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    if positive and not value > 0:
        raise ValueError(f"{name} must be positive")
    return float(value)


def validate_report(payload: object, size: int) -> dict[str, object]:
    """Return the report when it matches the result schema for ``size``."""
    if not isinstance(payload, dict):
        raise ValueError("report must be a JSON object")
    schema = _integer(payload.get("schema_version"), "schema_version")
    if schema != 1:
        raise ValueError("schema_version must be 1")
    reported = _integer(payload.get("size"), "size")
    if reported != size:
        raise ValueError(f"size {reported} does not match job size {size}")
    gpu = payload.get("gpu")
    if not isinstance(gpu, str) or gpu.strip() == "":
        raise ValueError("gpu must be a nonempty string")
    _finite(payload.get("elapsed_ms"), "elapsed_ms", positive=True)
    _finite(payload.get("mean"), "mean", positive=False)
    if payload.get("verified") is not True:
        raise ValueError("verified must be true")
    return payload


def _missing(stderr: str) -> bool:
    """True only when stderr positively says the object is absent."""
    text = stderr.lower()
    if any(marker in text for marker in _ACCESS_MARKERS):
        return False
    return any(marker in text for marker in _MISSING_MARKERS)


def _reject_constant(token: str) -> None:
    raise ValueError(f"nonstandard JSON number {token}")


def _run_aws(uri: str, timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "aws",
            "s3",
            "cp",
            uri,
            "-",
            "--endpoint-url",
            ENDPOINT,
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        timeout=timeout,
    )


def _fetch_report(size: int, job_id: str, prefix: str) -> dict[str, object]:
    """Read one report. Retry only a missing object, and only until the cap."""
    uri = f"s3://{BUCKET}/{prefix}/{size}.json"
    deadline = time.monotonic() + REPORT_SECONDS
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SystemExit(
                f"size {size}: job {job_id}: report missing at {uri} "
                f"after {REPORT_SECONDS}s"
            )
        try:
            completed = _run_aws(uri, remaining)
        except subprocess.TimeoutExpired as exc:
            raise SystemExit(
                f"size {size}: job {job_id}: retrieval timed out for {uri}"
            ) from exc
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr if isinstance(exc.stderr, str) else ""
            retry = (
                _missing(stderr)
                and time.monotonic() + REPORT_PAUSE < deadline
            )
            if retry:
                time.sleep(REPORT_PAUSE)
                continue
            if _missing(stderr):
                raise SystemExit(
                    f"size {size}: job {job_id}: report missing at "
                    f"{uri} after {REPORT_SECONDS}s"
                ) from exc
            detail = stderr.strip() or f"aws exited {exc.returncode}"
            raise SystemExit(
                f"size {size}: job {job_id}: cannot retrieve {uri}: "
                f"{detail}"
            ) from exc
        except OSError as exc:
            raise SystemExit(
                f"size {size}: job {job_id}: cannot retrieve {uri}: {exc}"
            ) from exc
        try:
            payload = json.loads(
                completed.stdout,
                parse_constant=_reject_constant,
            )
        except (json.JSONDecodeError, ValueError) as exc:
            raise SystemExit(
                f"size {size}: job {job_id}: malformed report at "
                f"{uri}: {exc}"
            ) from exc
        try:
            return validate_report(payload, size)
        except ValueError as exc:
            raise SystemExit(
                f"size {size}: job {job_id}: invalid report at "
                f"{uri}: {exc}"
            ) from exc


def _print_table(rows: list[dict[str, object]]) -> None:
    """Print size, gpu, elapsed_ms, mean, and verified."""
    print("\t".join(_COLUMNS))
    for row in rows:
        print("\t".join(str(row[name]) for name in _COLUMNS))


def main() -> None:
    """Submit three sizes, then collect each JSON report."""
    _require_sizes(SIZES)
    prefix = f"matrix-multiply/{uuid4().hex}"
    print(f"prefix {prefix}", flush=True)
    # --- orchestration: start ---
    config = Config()
    project_id = config.parent_id
    if not isinstance(project_id, str) or not project_id.strip():
        raise SystemExit("Nebius profile has no parent_id configured")
    sdk = SDK(config_reader=config, parent_id=project_id)
    try:
        client = JobServiceClient(sdk)
        jobs: list[tuple[int, str]] = []
        for size in SIZES:
            args = " ".join(
                shlex.quote(part)
                for part in ("-c", WORKER, prefix, str(size))
            )
            request = CreateJobRequest(
                metadata=ResourceMetadata(
                    parent_id=project_id,
                    name=f"job-{uuid4().hex[:12]}",
                ),
                spec=JobSpec(
                    image=IMAGE,
                    container_command="python",
                    args=args,
                    platform="gpu-h100-sxm",
                    preset="1gpu-16vcpu-200gb",
                    timeout=timedelta(seconds=3600),
                    shm_size_bytes=16 * 1024**3,
                    disk=JobSpec.DiskSpec(
                        type=ComputeDisk.DiskType.NETWORK_SSD,
                        size_bytes=250 * 1024**3,
                    ),
                    volumes=[
                        JobSpec.VolumeMount(
                            source=f"s3://{BUCKET}",
                            container_path="/data",
                            mode=JobSpec.VolumeMount.Mode.READ_WRITE,
                        )
                    ],
                ),
            )
            try:
                operation = client.create(request).wait()
                operation.sync_wait()
            except Exception as exc:
                raise SystemExit(
                    f"size {size}: submission failed: {exc}"
                ) from exc
            job_id = operation.resource_id
            if not isinstance(job_id, str) or not job_id:
                raise SystemExit(
                    f"size {size}: submission returned no job ID"
                )
            jobs.append((size, job_id))
            print(f"size {size}: {job_id}", flush=True)
        # --- orchestration: end ---

        rows: list[dict[str, object]] = []
        # --- orchestration: start ---
        for size, job_id in jobs:
            wait_deadline = time.monotonic() + WAIT_SECONDS
            while True:
                try:
                    job = client.get(GetJobRequest(id=job_id)).wait()
                except Exception as exc:
                    raise SystemExit(
                        f"size {size}: job {job_id}: {exc}"
                    ) from exc
                state = job.status.state.name
                if state in TERMINAL_STATES:
                    break
                remaining = wait_deadline - time.monotonic()
                if remaining <= 0:
                    raise SystemExit(
                        f"size {size}: job {job_id}: local wait timed "
                        f"out after {WAIT_SECONDS}s"
                    )
                time.sleep(min(POLL_SECONDS, remaining))
            if state != "COMPLETED":
                raise SystemExit(
                    f"size {size}: job {job_id} ended {state}"
                )
            # --- orchestration: end ---
            rows.append(_fetch_report(size, job_id, prefix))
    # --- orchestration: start ---
    finally:
        sdk.sync_close()
    # --- orchestration: end ---
    _print_table(rows)


if __name__ == "__main__":
    main()
