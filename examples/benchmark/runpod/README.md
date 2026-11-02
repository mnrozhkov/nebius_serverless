# RunPod Comparison Examples

Isolated [RunPod](https://docs.runpod.io/) reference examples (`runpod==2.0.0rc1`) for the two containerized SDK comparison tasks:

1. **`quickstart.py`** — run `nvidia-smi` on one requested H100 GPU and verify non-empty command output.
2. **`axolotl_lora.py`** — run `axolotl train /workspace/data/config.yaml` on the pre-built `docker.io/axolotlai/axolotl:main-20260309-py3.11-cu128-2.9.1` image on an H100 GPU (`min_cuda_version="12.8"`, `container_disk_gb=500`) with a 500 GB `runpod.NetworkVolume` mounted at `/workspace` and a 24h `timeout` wrapper.

This directory is a standalone Python project with its own `pyproject.toml` and `uv.lock` (`runpod==2.0.0rc1`). It is intentionally **not** a `uv` workspace member of the repository root so that `uv sync` at the root never installs `runpod`.

## Prerequisites

- Python `>=3.10` and [`uv`](https://docs.astral.sh/uv/)
- A RunPod account with API key and H100 GPU access

## Installation

Install the isolated environment inside `examples/benchmark/runpod`:

```bash
cd examples/benchmark/runpod && uv sync
```

Or manage it from the repository root with `--project examples/benchmark/runpod`:

```bash
uv sync --project examples/benchmark/runpod
```

## Authentication

Authenticate with the RunPod CLI (or export `RUNPOD_API_KEY`):

```bash
uv run --project examples/benchmark/runpod rp login
```

## Running the Examples

From the repository root:

```bash
uv run --project examples/benchmark/runpod rp flash dev --once examples/benchmark/runpod/quickstart.py
uv run --project examples/benchmark/runpod rp flash dev --once examples/benchmark/runpod/axolotl_lora.py
```

Or from inside `examples/benchmark/runpod`:

```bash
cd examples/benchmark/runpod
uv run rp flash dev --once quickstart.py
uv run rp flash dev --once axolotl_lora.py
```

## Key Model and Setup Differences vs. Nebius Cloud Jobs

- **Function/task decorator around `subprocess.run` vs. direct container command:** Like Modal, RunPod's SDK uses decorators (`@app.queue` / `@app.task` + `@runpod.local_entrypoint`) to execute Python functions remotely, so running a containerized CLI workload (`nvidia-smi` or `axolotl train`) requires wrapping `subprocess.run(...)` inside the decorated function.
- **Deadline enforcement in `@app.task`:** In `axolotl_lora.py`, `@app.task` wraps the `axolotl train` invocation in `timeout --kill-after=60s 24h` inside `subprocess.run(...)`, whereas `nebius_serverless` sets the job-level execution deadline declaratively via `timeout="24h"`.
- **Storage model:** RunPod mounts a `runpod.NetworkVolume("axolotl-workspace", size=500)` at `/workspace`, whereas `nebius_serverless` mounts Object Storage buckets (`s3://axolotl-data:/workspace/data:ro` and `s3://axolotl-artifacts:/workspace/artifacts:rw`).
