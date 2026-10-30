"""Canonical GPU matrix-multiplication worker and comparison conventions.

Pinned container image for Nebius batch comparison scripts:
- Image:
  ``pytorch/pytorch:2.6.0-cuda12.6-cudnn9-runtime``
  ``@sha256:f894dae26e1ee8557c544f9cfdb9dc011b1552bf3c1e656b422f2e221d380e40``
- PyTorch version: ``2.6.0`` (``2.6.0+cu126``)
- Python version: ``3.11.11``
- CUDA runtime version: ``12.6.3`` (cuDNN 9, Ubuntu 22.04 ``linux/amd64``)

Batch sizes:
- ``SIZES = (1024, 2048, 4096)``

Orchestration line-counting marker convention:
- Every runnable comparison script brackets provider orchestration code with
  exact comment pairs:
  - ``# --- orchestration: start ---``
  - ``# --- orchestration: end ---``
- Multiple start/end blocks may appear in a file (for example around
  provider SDK imports and around job submission/waiting/cleanup).
- The line counter excludes blank lines, comment lines (including the marker
  comments themselves), and module/function docstrings.
- Non-excluded lines inside ``# --- orchestration: start ---`` ..
  ``# --- orchestration: end ---`` are counted as *Orchestration* lines;
  remaining non-excluded lines are counted as *Workload and data* lines.

Runnable comparison scripts must embed ``matrix_multiply`` (or ``WORKER`` for
``python -c`` variants) directly rather than importing this module, so line
counts reflect all author-owned code. Offline tests compare each script's
embedded worker against this canonical definition.
"""

IMAGE = (
    "pytorch/pytorch"
    "@sha256:f894dae26e1ee8557c544f9cfdb9dc011b1552bf3c1e656b422f2e221d380e40"
)
PYTORCH_VERSION = "2.6.0"
PYTHON_VERSION = "3.11.11"
CUDA_VERSION = "12.6.3"
SIZES = (1024, 2048, 4096)

ORCHESTRATION_START = "# --- orchestration: start ---"
ORCHESTRATION_END = "# --- orchestration: end ---"


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
