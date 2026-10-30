# Modal Comparison Examples

Isolated [Modal](https://modal.com/docs/guide) reference examples for the two SDK comparison tasks in [`specs/sdk_copmarison.md`](../../specs/sdk_copmarison.md):

1. **`quickstart.py`** — run `nvidia-smi` on one requested H100 GPU and verify non-empty command output.
2. **`matrix_multiply.py`** — run the shared float32 CUDA matrix multiplication worker for sizes `1024`, `2048`, and `4096` in parallel via `.map()`, verify each returned summary, and print a compact results table.

This directory is a standalone Python project with its own `pyproject.toml` and `uv.lock` (`modal==1.6.3`). It is intentionally **not** a `uv` workspace member of the repository root so that `uv sync` at the root never installs `modal`.

## Prerequisites

- Python `>=3.10` and [`uv`](https://docs.astral.sh/uv/)
- A Modal account with H100 GPU quota

## Installation

Install the isolated environment inside `examples/modal`:

```bash
cd examples/modal && uv sync
```

Or manage it from the repository root with `--project examples/modal`:

```bash
uv sync --project examples/modal
```

## Authentication

Configure Modal credentials (writes a token to `~/.modal.toml` or uses `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET`):

```bash
cd examples/modal
uv run modal setup
```

From the repository root:

```bash
uv run --project examples/modal modal setup
```

## Running the Examples

From inside `examples/modal`:

```bash
uv run modal run quickstart.py
uv run modal run matrix_multiply.py
```

Or from the repository root:

```bash
uv run --project examples/modal modal run examples/modal/quickstart.py
uv run --project examples/modal modal run examples/modal/matrix_multiply.py
```

## Key Model and Setup Differences vs. Nebius Cloud Jobs

- **`gpu="H100!"` vs. auto-upgrade:** Modal allows `gpu="H100"` requests to silently upgrade to an H200 when inventory prefers it. Both scripts specify `gpu="H100!"` (with the trailing `!`) to disable auto-upgrading and keep the hardware request aligned with the explicit H100 selection in the Nebius examples.
- **Container pool reuse vs. per-job isolation:** `run_matrix_multiply.map(SIZES)` dispatches the three inputs across an autoscaling Modal function container pool. Depending on warm worker availability and concurrency, a single container may execute more than one input sequentially, whereas each `Job.create()` in Nebius Serverless provisions an isolated single-run job container.
- **Image build setup (`modal.Image`):** Instead of referencing a pre-built Docker registry digest directly, `matrix_multiply.py` declares `modal.Image.debian_slim(python_version="3.11").pip_install("torch==2.6.0")`. Modal builds and caches this container image remotely on first execution; that image definition is counted as non-Python environment setup in the comparison alongside the orchestration lines.
- **Direct Python return values:** Modal serializes the `str` output of `run_nvidia_smi.remote()` and the `dict[str, object]` summaries of `run_matrix_multiply.map(SIZES)` back to the local caller without requiring an intermediate object-storage bucket mount.
- **Timeouts and cleanup:** `timeout=3600` sets the per-invocation remote execution deadline (1 hour) on the Modal function. `modal run` creates an ephemeral app that tears down when the CLI exits; if a local terminal session is interrupted, inspect or stop lingering ephemeral apps with `uv run modal app list` and `uv run modal app stop <app-id>`.
