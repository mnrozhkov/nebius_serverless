# SDK Comparison Utilities and Focused Quickstart

This directory contains the shared conventions, measurement runner, and focused Designed Nebius SDK quickstart for [`docs/sdk-comparison.md`](../../docs/sdk-comparison.md) (implementing [`specs/sdk_copmarison.md`](../../specs/sdk_copmarison.md)):

- **`quickstart.py`** — the focused Designed Nebius SDK (`nebius_serverless`) quickstart used in Panel 2 of the SDK comparison (`Job`, `create()`, `print(run.id)`, `wait()`, and `status == "COMPLETED"` check). Note that [`examples/job_quickstart.py`](../job_quickstart.py) remains the full Cloud Jobs contract recipe (which additionally exercises `run.get()`, `run.cancel()`, and `ns.jobs.get(saved_id)`).
- **`worker.py`** — canonical definition of the shared GPU matrix multiplication workload (`matrix_multiply(size: int)` and `WORKER` string for `python -c` variants), pinned container image constants, and orchestration marker conventions. Runnable comparison scripts embed their own copy of `matrix_multiply` / `WORKER` so line counts include all author-owned code; offline tests verify verbatim equality against `worker.py`.
- **`measure.py`** — reproducible line-count and SHA-256 hash calculator across all 10 task variants (Quickstart and Batch across Official Nebius SDK, Designed Nebius SDK, Modal, RunPod App SDK beta, and RunPod Endpoint SDK client + worker).

## Running the Focused Quickstart

```bash
uv run python examples/comparison/quickstart.py
```

Requires an active Nebius CLI profile (`~/.nebius/config.yaml`) with `parent-id` configured, `eu-north1` H100 quota (`gpu-h100-sxm` / `1gpu-16vcpu-200gb`), and a single default subnet. Inspect command output after completion with:

```bash
nebius ai job logs <id>
```

## Computing Line Counts and SHA-256 Hashes

```bash
uv run python examples/comparison/measure.py
uv run python examples/comparison/measure.py --json
```
