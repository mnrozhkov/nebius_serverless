# Official Nebius Python SDK Examples (`nebius==0.6.27`)

Baseline scripts for the SDK comparison using the official `nebius` Python SDK (`nebius==0.6.27`) synchronous interface (`JobServiceClient`, `CreateJobRequest`, `GetJobRequest`, `operation.wait()`, `operation.sync_wait()`).

Neither script imports `nebius_serverless` or `asyncio`. Both resolve the same H100 settings in `eu-north1` that `nebius_serverless` selects for `gpu="h100"` and `timeout="1h"`:

- `platform="gpu-h100-sxm"`
- `preset="1gpu-16vcpu-200gb"`
- `timeout=timedelta(seconds=3600)` (1 hour remote execution deadline)
- `disk`: `NETWORK_SSD`, `250 GiB` (`250 * 1024**3` bytes)
- `shm_size_bytes`: `16 GiB` (`16 * 1024**3` bytes)
- Pricing: on-demand (no preemptible flags)

## Prerequisites

1. **Repository environment**: `nebius==0.6.27` is already pinned in the root `pyproject.toml`. Install dependencies from the repository root if needed:
   ```bash
   uv sync
   ```
2. **Nebius CLI profile & project**: An active Nebius CLI profile (`~/.nebius/config.yaml`) with valid credentials and a configured `parent-id` (`project_id`).
3. **Region & GPU quota**: A project in `eu-north1` (where `gpu-h100-sxm` / `1gpu-16vcpu-200gb` is available) with quota for at least 1 H100 GPU for `quickstart.py`, and up to 3 concurrent H100 GPUs for `matrix_multiply.py`.
4. **Subnet**: A single default subnet in the project (if the project has multiple subnets, `JobSpec.subnet_id` must be specified explicitly).
5. **Object Storage bucket & AWS CLI (`matrix_multiply.py` only)**:
   - An existing Nebius Object Storage bucket matching `BUCKET` (default `"acceptance-bucket"`) in the region matching `ENDPOINT` (default `"https://storage.eu-north1.nebius.cloud"`), writable by the job mount `s3://<BUCKET>:/data:rw`.
   - AWS CLI v2 configured with credentials that can read `s3://<BUCKET>/<prefix>/<size>.json` at `ENDPOINT` (and delete objects during cleanup).

## Running the Examples

Run both scripts from the repository root using `uv run`:

### 1. Quickstart (`nvidia-smi`)

```bash
uv run python examples/official/quickstart.py
```

Submits one H100 job running `nvidia-smi` on `nvidia/cuda:13.1.1-runtime-ubuntu24.04`, prints the accepted job ID (`operation.resource_id`), polls `GetJob` until the state is terminal (`COMPLETED`, `FAILED`, `CANCELLED`, or `ERROR`), and raises `RuntimeError` unless the final state is `COMPLETED`.

Because the Nebius Jobs API does not return container stdout in the `GetJob` response, inspect the GPU output separately with the Nebius CLI:

```bash
nebius ai job logs <id>
```

### 2. Batch GPU Matrix Multiplication

```bash
uv run python examples/official/matrix_multiply.py
```

Submits all three H100 jobs (`SIZES = (1024, 2048, 4096)`) on the pinned image `pytorch/pytorch@sha256:f894dae26e1ee8557c544f9cfdb9dc011b1552bf3c1e656b422f2e221d380e40` (`pytorch/pytorch:2.6.0-cuda12.6-cudnn9-runtime`) before waiting on any job completion. After each job reaches `COMPLETED`, the script fetches `s3://<BUCKET>/<prefix>/<size>.json` via the AWS CLI (retrying missing objects for up to 60 seconds at 2-second intervals), validates the JSON report schema and numerical verification flag, and prints a tab-separated summary table (`size`, `gpu`, `elapsed_ms`, `mean`, `verified`).

## Timeout Semantics

- **Remote job deadline (`JobSpec.timeout = timedelta(seconds=3600)`)**: Instructs Nebius Serverless AI Jobs to terminate the container if execution exceeds 1 hour.
- **Local polling deadline (`WAIT_SECONDS = 5400` in `matrix_multiply.py`)**: Bounds how long the local Python process polls `GetJobRequest`. A local polling timeout or local process exit does **not** cancel or stop already accepted remote jobs.
- **Result retrieval window (`REPORT_SECONDS = 60`, `REPORT_PAUSE = 2`)**: Bounds how long `matrix_multiply.py` retries `aws s3 cp` when the report object is not yet visible after `COMPLETED`.

## Manual Cleanup

The scripts do not automatically cancel or delete remote jobs or Object Storage reports, preserving logs and artifacts for inspection. Clean up resources manually after inspecting results:

```bash
nebius ai job delete <id>
aws s3 rm --recursive "s3://<bucket>/matrix-multiply/<uuid>/" \
  --endpoint-url https://storage.eu-north1.nebius.cloud
```
