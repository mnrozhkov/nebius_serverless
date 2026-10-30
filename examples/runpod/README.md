# RunPod Comparison Examples

Isolated [RunPod](https://docs.runpod.io/) reference examples for the two SDK comparison tasks in [`specs/sdk_copmarison.md`](../../specs/sdk_copmarison.md):

1. **Quickstart (`nvidia-smi`)** — run `nvidia-smi` on one requested H100 GPU and verify non-empty output.
2. **Batch GPU matrix multiplication** — run the shared float32 CUDA matrix multiplication worker for sizes `1024`, `2048`, and `4096` (submitting all three before waiting), verify each returned summary, and print a compact results table.

RunPod currently exposes two distinct Python workflows, so this project keeps them in separate tracks:

- **`app/` — RunPod App SDK (beta, `runpod==2.0.0rc1`):** author remote GPU functions in a single file with `runpod.App`, `@app.queue(gpu="H100", ...)`, and `@runpod.local_entrypoint`, then run or deploy them through the `rp flash` CLI.
- **`endpoint/` — RunPod Serverless Endpoint SDK:** deploy a container worker running `runpod.serverless.start({"handler": handler})` first, then submit jobs from a separate caller script using `runpod.Endpoint(endpoint_id).run(...)`. Keeping `*_worker.py`, `Dockerfile`, `requirements.txt`, and `*_client.py` side by side ensures worker packaging and deployment are explicitly visible rather than hidden behind a short client snippet.

This directory is a standalone Python project with its own `pyproject.toml` and `uv.lock` (`runpod==2.0.0rc1`). It is intentionally **not** a `uv` workspace member of the repository root so that `uv sync` at the root never installs `runpod`.

## Prerequisites

- Python `>=3.10` and [`uv`](https://docs.astral.sh/uv/)
- A RunPod account with API key and H100 Serverless GPU access
- Docker (with `linux/amd64` build support) and a container registry account for the `endpoint/` track

## Installation

Install the isolated environment inside `examples/runpod`:

```bash
cd examples/runpod && uv sync
```

Or manage it from the repository root with `--project examples/runpod`:

```bash
uv sync --project examples/runpod
```

---

## Track 1: RunPod App SDK (Beta) — `examples/runpod/app/`

### Files

- `app/quickstart.py` — defines `@app.queue(gpu="H100", execution_timeout_ms=3600000)` `run_nvidia_smi()` and invokes `run_nvidia_smi.remote()` from `@runpod.local_entrypoint`.
- `app/matrix_multiply.py` — embeds the canonical `matrix_multiply(size: int)` worker, declares `@app.queue(gpu="H100", dependencies=["torch==2.6.0"], execution_timeout_ms=3600000)`, submits all three sizes `(1024, 2048, 4096)` via `.spawn(size)` before waiting with `job.result(timeout=3600)`, validates the returned summaries, and prints the results table.

### Authentication

Authenticate with the RunPod CLI (or export `RUNPOD_API_KEY`):

```bash
uv run --project examples/runpod rp login
```

### Running in a Development Session

`rp flash dev` provisions temporary live endpoints for the module, executes its `@runpod.local_entrypoint`, and tears the temporary endpoints down on exit (pass `--once` to run once and exit immediately):

```bash
uv run --project examples/runpod rp flash dev --once examples/runpod/app/quickstart.py
uv run --project examples/runpod rp flash dev --once examples/runpod/app/matrix_multiply.py
```

Or from inside `examples/runpod`:

```bash
cd examples/runpod
uv run rp flash dev --once app/quickstart.py
uv run rp flash dev --once app/matrix_multiply.py
```

### Deploying and Cleaning Up Persistent App Endpoints

To package and deploy the app endpoints persistently:

```bash
uv run --project examples/runpod rp flash deploy examples/runpod/app
```

To tear down deployed app endpoints when finished:

```bash
uv run --project examples/runpod rp flash undeploy --app nebius-comparison-quickstart --yes
uv run --project examples/runpod rp flash undeploy --app nebius-comparison-matrix-multiply --yes
```

---

## Track 2: RunPod Serverless Endpoint SDK — `examples/runpod/endpoint/`

The established `runpod.Endpoint` client assumes a worker image has already been built, pushed to a container registry, and attached to a configured Serverless Endpoint. Both the worker and caller files are part of the total authoring surface.

### Files

- `endpoint/quickstart_worker.py` & `endpoint/quickstart_client.py` — worker handler executing `nvidia-smi` via `runpod.serverless.start({"handler": handler})`, paired with the caller script that submits via `endpoint.run(...)`, prints `job.job_id`, waits via `job.output(timeout=3600)`, checks `job.status() == "COMPLETED"`, and prints `nvidia-smi` output.
- `endpoint/matrix_worker.py` & `endpoint/matrix_client.py` — worker handler embedding the canonical `matrix_multiply(size: int)` function, paired with the caller script that submits all three sizes `(1024, 2048, 4096)` via `endpoint.run({"size": size})` before waiting on their outputs, validates each summary, and prints the results table.
- `endpoint/Dockerfile` & `endpoint/requirements.txt` — container build definition starting from the pinned `pytorch/pytorch:2.6.0-cuda12.6-cudnn9-runtime` digest and installing `runpod==2.0.0rc1`.

### Step 1: Build and Push the Worker Image

Build the worker image for `linux/amd64` (set `WORKER_SCRIPT=quickstart_worker.py` for the quickstart worker or `WORKER_SCRIPT=matrix_worker.py` for the matrix worker) and push it to your container registry:

```bash
docker build --platform linux/amd64 \
  --build-arg WORKER_SCRIPT=matrix_worker.py \
  -t <registry>/<namespace>/runpod-comparison-worker:latest \
  examples/runpod/endpoint
docker push <registry>/<namespace>/runpod-comparison-worker:latest
```

### Step 2: Create the RunPod Serverless Endpoint

1. In the RunPod console (or via the RunPod API), create a **Serverless Endpoint** using `<registry>/<namespace>/runpod-comparison-worker:latest`.
2. Select the **H100 80GB** GPU pool (`ADA_80_PRO`) with 1 GPU per worker and an execution timeout of 3,600 seconds.
3. Copy the resulting Endpoint ID.

### Step 3: Run the Caller Client

Export `RUNPOD_API_KEY` and `RUNPOD_ENDPOINT_ID`, then run the corresponding client script:

```bash
export RUNPOD_API_KEY="<your-runpod-api-key>"
export RUNPOD_ENDPOINT_ID="<your-endpoint-id>"

# When the endpoint runs quickstart_worker.py:
uv run --project examples/runpod python examples/runpod/endpoint/quickstart_client.py

# When the endpoint runs matrix_worker.py:
uv run --project examples/runpod python examples/runpod/endpoint/matrix_client.py
```

### Cleanup

Delete the Serverless Endpoint (or set max workers to `0`) in the RunPod console and remove the pushed container image from your registry when finished.

---

## Key Model and Setup Differences vs. Nebius Cloud Jobs

- **Pool-based GPU selection (`gpu="H100"` / `ADA_80_PRO`):** In `runpod==2.0.0rc1`, `gpu="H100"` resolves to the `ADA_80_PRO` pool covering `NVIDIA H100 PCIe`, `NVIDIA H100 80GB HBM3`, and `NVIDIA H100 NVL`, whereas Nebius Cloud Jobs targets a specific platform and preset (`gpu-h100-sxm` / `1gpu-16vcpu-200gb`).
- **Queue worker reuse vs. per-job container isolation:** Both `@app.queue` and Serverless Endpoints dispatch jobs onto a queue backed by autoscaling workers that can process multiple queued requests over their lifetime, whereas each `Job.create()` in Nebius Serverless runs an isolated job container.
- **Concurrent submission via `.spawn()` and `endpoint.run()`:** In `app/matrix_multiply.py`, `run_matrix_multiply.spawn(size)` enqueues all three sizes before `job.result(timeout=3600)` waits for completion. In `endpoint/matrix_client.py`, `endpoint.run({"size": size})` enqueues all three requests before `job.output(timeout=3600)` polls for each result.
- **Direct output return vs. object storage mount:** Both RunPod tracks return small JSON outputs (`stdout` or the matrix summary dict) directly through the RunPod job status/result API without mounting an S3 bucket.
