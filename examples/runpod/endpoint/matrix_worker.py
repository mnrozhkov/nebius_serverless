"""RunPod Serverless Endpoint worker handler for GPU matrix multiplication."""

# --- orchestration: start ---
import runpod

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
def handler(job: dict[str, object]) -> dict[str, object]:
    """Handle one RunPod serverless job request for a single matrix size."""
    job_input = job.get("input")
    if not isinstance(job_input, dict) or "size" not in job_input:
        raise ValueError("job['input']['size'] is required")
    return matrix_multiply(int(job_input["size"]))


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
# --- orchestration: end ---
