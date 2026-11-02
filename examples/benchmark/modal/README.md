# Modal Comparison Examples

Isolated [Modal](https://modal.com/docs/guide) reference examples for the two containerized SDK comparison tasks:

1. **`quickstart.py`** — run `nvidia-smi` on one requested H100 GPU and verify non-empty command output.
2. **`axolotl_lora.py`** — run `axolotl train /workspace/data/config.yaml` on the pre-built `docker.io/axolotlai/axolotl:main-20260309-py3.11-cu128-2.9.1` image on an H100 GPU with a 500 GiB ephemeral disk, 24h timeout, and mounted Modal Volumes (`axolotl-data` and `axolotl-artifacts`), committing `artifacts` on completion.

This directory is a standalone Python project with its own `pyproject.toml` and `uv.lock` (`modal==1.6.3`). It is intentionally **not** a `uv` workspace member of the repository root so that `uv sync` at the root never installs `modal`.

## Prerequisites

- Python `>=3.10` and [`uv`](https://docs.astral.sh/uv/)
- A Modal account with H100 GPU quota

## Installation

Install the isolated environment inside `examples/benchmark/modal`:

```bash
cd examples/benchmark/modal && uv sync
```

Or manage it from the repository root with `--project examples/benchmark/modal`:

```bash
uv sync --project examples/benchmark/modal
```

## Authentication

Configure Modal credentials (writes a token to `~/.modal.toml` or uses `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET`):

```bash
uv run --project examples/benchmark/modal modal setup
```

## Running the Examples

From the repository root:

```bash
uv run --project examples/benchmark/modal modal run examples/benchmark/modal/quickstart.py
uv run --project examples/benchmark/modal modal run examples/benchmark/modal/axolotl_lora.py
```

Or from inside `examples/benchmark/modal`:

```bash
cd examples/benchmark/modal
uv run modal run quickstart.py
uv run modal run axolotl_lora.py
```

## Key Model and Setup Differences vs. Nebius Cloud Jobs

- **Function decorator around `subprocess.run` vs. direct container command:** Because Modal's primary execution primitive is a decorated Python function (`@app.function`), running an existing CLI command (`nvidia-smi` or `axolotl train /workspace/data/config.yaml`) requires wrapping `subprocess.run(...)` inside a Python function and invoking `.remote()` from `@app.local_entrypoint()`, whereas `nebius_serverless` passes `command` directly to the container runtime.
- **Modal Volumes + `artifacts.commit()` vs. S3 volume mounts:** Modal mounts `modal.Volume.from_name(...)` objects at `/workspace/data` and `/workspace/artifacts` and calls `artifacts.commit()` after `subprocess.run(...)` finishes, whereas `nebius_serverless` mounts Object Storage buckets via CLI-compatible strings (`s3://axolotl-data:/workspace/data:ro` and `s3://axolotl-artifacts:/workspace/artifacts:rw`).
- **Disk and timeout units:** Modal configures disk in MiB (`ephemeral_disk=500 * 1024`) and timeout in seconds (`timeout=24 * 60 * 60`), whereas `nebius_serverless` accepts human-readable unit strings (`disk="500Gi"`, `timeout="24h"`).
