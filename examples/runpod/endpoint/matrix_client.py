"""Caller client for the RunPod Serverless Endpoint matrix multiplication."""

import math
import os

# --- orchestration: start ---
import runpod

# --- orchestration: end ---

SIZES = (1024, 2048, 4096)


def validate_summary(
    summary: dict[str, object], expected_size: int
) -> dict[str, object]:
    """Validate one matrix multiplication summary against the schema."""
    if not isinstance(summary, dict):
        raise ValueError(f"Expected dict summary, got {type(summary)!r}")
    schema_version = summary.get("schema_version")
    if isinstance(schema_version, bool) or schema_version != 1:
        raise ValueError(f"Invalid schema_version: {schema_version!r}")
    size = summary.get("size")
    if isinstance(size, bool) or size != expected_size:
        raise ValueError(
            f"Summary size {size!r} does not match {expected_size}"
        )
    gpu = summary.get("gpu")
    if not isinstance(gpu, str) or not gpu.strip():
        raise ValueError(f"Invalid gpu name: {gpu!r}")
    elapsed_ms = summary.get("elapsed_ms")
    if (
        isinstance(elapsed_ms, bool)
        or not isinstance(elapsed_ms, (int, float))
        or not math.isfinite(elapsed_ms)
        or elapsed_ms <= 0
    ):
        raise ValueError(f"Invalid elapsed_ms: {elapsed_ms!r}")
    mean = summary.get("mean")
    if (
        isinstance(mean, bool)
        or not isinstance(mean, (int, float))
        or not math.isfinite(mean)
    ):
        raise ValueError(f"Invalid mean: {mean!r}")
    if summary.get("verified") is not True:
        raise ValueError(f"Summary not verified: {summary.get('verified')!r}")
    return summary


def main() -> None:
    """Submit all three sizes to the RunPod endpoint and print results."""
    # --- orchestration: start ---
    runpod.api_key = os.environ["RUNPOD_API_KEY"]
    endpoint = runpod.Endpoint(os.environ["RUNPOD_ENDPOINT_ID"])
    jobs = []
    for size in SIZES:
        job = endpoint.run({"size": size})
        print(f"size {size}: {job.job_id}", flush=True)
        jobs.append((size, job))

    summaries: list[dict[str, object]] = []
    for size, job in jobs:
        output = job.output(timeout=3600)
        status = job.status()
        if status != "COMPLETED":
            raise RuntimeError(f"size {size}: {job.job_id}: {status}")
        summaries.append(output)
    # --- orchestration: end ---

    rows = [
        validate_summary(summary, size)
        for size, summary in zip(SIZES, summaries, strict=True)
    ]
    print("size\tgpu\telapsed_ms\tmean\tverified")
    for row in rows:
        print(
            f"{row['size']}\t{row['gpu']}\t"
            f"{row['elapsed_ms']:.3f}\t{row['mean']:.6f}\t{row['verified']}"
        )


if __name__ == "__main__":
    main()
