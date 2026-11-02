# Official Nebius Python SDK Examples (`nebius==0.6.27`)

Baseline scripts for the SDK comparison using the official `nebius` Python SDK (`nebius==0.6.27`) synchronous interface (`JobServiceClient`, `CreateJobRequest`, `GetJobRequest`, `operation.wait()`). Completion is a `GetJob` poll. `operation.sync_wait()` is not used, because that waits until the container exits and would duplicate the poll.

Neither script imports `nebius_serverless` or `asyncio`. Both select the same H100 platform and preset in `eu-north1` that `nebius_serverless` resolves for [`examples/job_quickstart.py`](../../job_quickstart.py) and [`examples/train/axolotl_lora.py`](../../train/axolotl_lora.py). Disk size and `/dev/shm` are left unset except for the Axolotl disk, so the platform default applies. `nebius_serverless` still sends 250 GiB and 16 GiB on the quickstart, and 16 GiB `/dev/shm` on Axolotl.

- `platform="gpu-h100-sxm"`
- `preset="1gpu-16vcpu-200gb"`
- `quickstart.py`: on-demand pricing, `timeout=timedelta(seconds=3600)` (1h). No disk and no `shm_size_bytes`.
- `axolotl_lora.py`: spot pricing (`preemptible=True`, `PricingModelSpec(follows_spot_price=FollowsSpotPriceSpec())`), `timeout=timedelta(seconds=24 * 3600)` (24h), `500 GiB` `NETWORK_SSD`, and `s3://axolotl-data` (`READ_ONLY` at `/workspace/data`) + `s3://axolotl-artifacts` (`READ_WRITE` at `/workspace/artifacts`) volume mounts. No `shm_size_bytes`.

## Prerequisites

1. **Repository environment**: `nebius==0.6.27` is already pinned in the root `pyproject.toml`. Install dependencies from the repository root if needed:
   ```bash
   uv sync
   ```
2. **Nebius CLI profile & project**: An active Nebius CLI profile (`~/.nebius/config.yaml`) with valid credentials and a configured `parent-id` (`project_id`).
3. **Region & GPU quota**: A project in `eu-north1` (where `gpu-h100-sxm` / `1gpu-16vcpu-200gb` is available) with H100 GPU quota.
4. **Subnet**: A single default subnet in the project (if the project has multiple subnets, `JobSpec.subnet_id` must be specified explicitly).
5. **Object Storage buckets (`axolotl_lora.py` only)**:
   - `s3://axolotl-data` containing `config.yaml` and training inputs (mounted read-only at `/workspace/data`).
   - `s3://axolotl-artifacts` writable by the job mount at `/workspace/artifacts` to persist trained model checkpoints.

## Running the Examples

Run both scripts from the repository root using `uv run`:

### 1. Quickstart (`nvidia-smi`)

```bash
uv run python examples/benchmark/nebius/quickstart.py
```

Submits one H100 job running `nvidia-smi` on `nvidia/cuda:13.1.1-runtime-ubuntu24.04`, polls `GetJob` until the state is terminal (`COMPLETED`, `FAILED`, `CANCELLED`, or `ERROR`), and raises `RuntimeError` unless the final state is `COMPLETED`. The job id is `operation.resource_id` and is not printed.

Because the Nebius Jobs API does not return container stdout in the `GetJob` response, inspect the GPU output separately with the Nebius CLI:

```bash
nebius ai job logs <id>
```

### 2. Axolotl Fine-Tuning (`axolotl train`)

```bash
uv run python examples/benchmark/nebius/axolotl_lora.py
```

Submits one spot H100 job running `bash -lc 'axolotl train /workspace/data/config.yaml'` on `docker.io/axolotlai/axolotl:main-20260309-py3.11-cu128-2.9.1` with a `500 GiB` disk, `24h` timeout, and S3 volume mounts (`/workspace/data` and `/workspace/artifacts`), then polls `GetJob` until `COMPLETED`.
