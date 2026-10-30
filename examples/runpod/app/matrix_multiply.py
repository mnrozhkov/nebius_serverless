"""Run three GPU matrix multiplications on RunPod App SDK (beta) H100s."""

import math

# --- orchestration: start ---
import runpod

# --- orchestration: end ---

SIZES = (1024, 2048, 4096)

# --- orchestration: start ---
app = runpod.App("nebius-comparison-matrix-multiply")
# --- orchestration: end ---


def matrix_multiply(size: int) -> dict[str, object]:
    """Run and verify a CUDA float32 matrix multiplication."""
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


# --- orchestration: start ---
@app.queue(
    gpu="H100",
    dependencies=["torch==2.6.0"],
    execution_timeout_ms=3600000,
)
def run_matrix_multiply(size: int) -> dict[str, object]:
    """Execute one matrix multiplication on a remote RunPod H100 worker."""
    return matrix_multiply(size)


# --- orchestration: end ---


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


# --- orchestration: start ---
@runpod.local_entrypoint
def main() -> None:
    """Spawn all three matrix sizes on RunPod and print verified results."""
    jobs = [(size, run_matrix_multiply.spawn(size)) for size in SIZES]
    for size, job in jobs:
        print(f"size {size}: {job.id}", flush=True)
    summaries = [job.result(timeout=3600) for _, job in jobs]
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
