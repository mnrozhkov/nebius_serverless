# Examples

Scripts below use the active Nebius profile and call `create()`. `create(dry_run=True)` is a library call: it prints the request and does not create a job. Run a script only when the project, region, and quota are authorized.

The alias for `gpu` must exist in that region. See the [alias table](reference.md#gpu-and-cpu-aliases). Logs are `nebius ai job logs <id>`.

Examples are grouped by use case. Settings other than a YAML path live in the Python file. The YAML runner takes `--config`.

| Path | Use case |
| --- | --- |
| `examples/job_quickstart.py` | One `nvidia-smi` job, the README recipe |
| `examples/from_yaml/` | That same recipe loaded from YAML |
| `examples/train/` | Axolotl fine-tune |
| `examples/batch/matrix_multiply.py` | Three GPU matrix multiplications, one size per job |
| `examples/comparison/` | Side-by-side [SDK comparison](sdk-comparison.md) (Official Nebius, Designed Nebius, Modal, RunPod) |

## Quickstart

One on-demand H100 job, the same recipe as the README. In `eu-north1`, `gpu="h100"` selects `gpu-h100-sxm` and `1gpu-16vcpu-200gb`. Omit `gpu` for a CPU machine (`cpu-d3`, `2vcpu-8gb`). `pricing="spot"` on that machine raises `UnsupportedFeature`.

`examples/job_quickstart.py`:

```python
import nebius_serverless as ns

job = ns.Job(
    ["nvidia-smi"],
    image="nvidia/cuda:13.1.1-runtime-ubuntu24.04",
    gpu="h100",
    timeout="1h",
)
print(job.create(dry_run=True))

run = job.create()
print(run.id)
record = run.get()
record = run.wait()
saved_id = run.id
loaded = ns.jobs.get(saved_id)
print(loaded.status)
```

The same recipe as YAML, `examples/from_yaml/nvidia_smi.yaml`, run by `examples/from_yaml/nvidia_smi_yaml.py`:

```yaml
schema_version: 1
kind: job
image: nvidia/cuda:13.1.1-runtime-ubuntu24.04
command: ["nvidia-smi"]
gpu: h100
timeout: 1h
```

```python
job = ns.Job.from_yaml("examples/from_yaml/nvidia_smi.yaml")
print(job.create(dry_run=True))
```

With a profile, both descriptions match apart from the generated name.

```bash
python examples/job_quickstart.py
python examples/from_yaml/nvidia_smi_yaml.py --config examples/from_yaml/nvidia_smi.yaml
```

The YAML runner waits until `status.state` is `COMPLETED`.

## Train

One spot GPU job. The full cookbook command is `examples/train/axolotl_lora.py`. In `eu-north1`, `gpu="h100"` selects `gpu-h100-sxm` and `1gpu-16vcpu-200gb`. Shared memory stays the `16Gi` default. The published command does not mount a volume.

```python
job = ns.Job(
    ["bash", "-lc", "axolotl train /workspace/data/config.yaml"],
    image="docker.io/axolotlai/axolotl:main-20260309-py3.11-cu128-2.9.1",
    gpu="h100",
    pricing="spot",
    disk="500Gi",
    timeout="24h",
)
print(job.create(dry_run=True))
run = job.create()
record = run.wait()
```

```bash
python examples/train/axolotl_lora.py
```

## Batch

Three independent GPU jobs, one matrix size each: `1024`, `2048`, and `4096`. There is no `.map()`. `examples/batch/matrix_multiply.py` submits every job, prints each id, then waits and reads a JSON report per size. Matrices are created on the GPU. Object Storage is used only to bring back the small reports. The jobs may run at the same time. The script does not promise that they start together, or that the batch finishes sooner than the same jobs one after another.

Set `BUCKET` to an existing bucket and keep `ENDPOINT` on that bucket’s region. The file ships `ENDPOINT` as `https://storage.eu-north1.nebius.cloud`. The active Nebius profile must be allowed to create jobs in a region where `gpu="h100"` exists. In `eu-north1` that alias is `gpu-h100-sxm` / `1gpu-16vcpu-200gb`. Quota has to cover up to three one-GPU H100 jobs, because overlap is allowed. The AWS CLI (v2) needs credentials that can read the report objects at `ENDPOINT`, and delete them when you clean up. The job mount `s3://<bucket>:/data:rw` has to be able to write those objects. No input files are uploaded. The controller does not import PyTorch.

The image is pinned by digest, checked against the `linux/amd64` manifest of `pytorch/pytorch:2.6.0-cuda12.6-cudnn9-runtime` (`pytorch/pytorch:2.6.0-cuda12.6-cudnn9-runtime@sha256:f894dae26e1ee8557c544f9cfdb9dc011b1552bf3c1e656b422f2e221d380e40`):

| | |
| --- | --- |
| digest | `pytorch/pytorch@sha256:f894dae26e1ee8557c544f9cfdb9dc011b1552bf3c1e656b422f2e221d380e40` |
| PyTorch | 2.6.0 (`2.6.0+cu126`) |
| Python | 3.11.11 |
| CUDA | 12.6.3 |
| cuDNN | 9, as named by that tag |
| base | Ubuntu 22.04 |

The worker sets `torch.backends.cuda.matmul.allow_tf32 = False` and `torch.set_float32_matmul_precision("highest")` so the float32 multiply uses full FP32 rather than a default that can change. It requires CUDA, checks `[[1, 2], [3, 4]] @ [[5, 6], [7, 8]]`, then checks the shape, finiteness, and nine sampled entries of the large product. A failed check does not write a success report. Each report is `/data/<prefix>/<size>.json` with `schema_version` 1, `size`, `gpu`, `elapsed_ms`, `mean`, and `verified: true`. See [SDK comparison](sdk-comparison.md) for the same workload beside the official Nebius SDK, Modal, and RunPod.

`timeout="1h"` is the remote Jobs deadline. `run.wait(timeout=5400)` only stops the local poll; it does not cancel the job. After `COMPLETED`, the script polls the report for at most 60 seconds, every 2 seconds, and only when the object is missing. An authentication failure, malformed JSON, or an invalid report stops immediately. Pricing stays the on-demand default.

```bash
uv run python examples/batch/matrix_multiply.py
```

```python
run = ns.Job(
    ["python", "-c", WORKER, prefix, str(size)],
    image=IMAGE,
    gpu="h100",
    timeout="1h",
    volumes=[f"s3://{BUCKET}:/data:rw"],
).create()
```

The script prints the object prefix and each job id as soon as create is accepted, then a table. The numbers below are an illustration. Timings, means, and the GPU name are not fixed results. On a real H100 the `gpu` column should name an H100; a different device means the allocation did not match `gpu="h100"`.

```text
prefix matrix-multiply/0124abcd0124abcd0124abcd0124abcd
size 1024: bt1example1024
size 2048: bt1example2048
size 4096: bt1example4096
size    gpu                     elapsed_ms    mean      verified
1024    NVIDIA H100 80GB HBM3   12.5          0.0011    True
2048    NVIDIA H100 80GB HBM3   48.2          -0.0003   True
4096    NVIDIA H100 80GB HBM3   190.4         0.0004    True
```

The script’s own table is tab-separated with the columns `size`, `gpu`, `elapsed_ms`, `mean`, and `verified`.

An error stops the script and includes the size and, once create has returned, the job id. Jobs already accepted keep running. Nothing is resubmitted, cancelled, or deleted. A local wait timeout does not stop the remote container. Cleanup is manual, and only for this invocation’s ids and prefix:

```bash
nebius ai job delete <id>
aws s3 rm --recursive "s3://<bucket>/matrix-multiply/<uuid>/" \
  --endpoint-url https://storage.eu-north1.nebius.cloud
```

## Reload a saved id

`run.id` is the handle. `jobs.get` performs one get and does not create again.

```python
saved_id = run.id
loaded = ns.jobs.get(saved_id)
print(loaded.status)
```

## Cancel

`cancel` returns when the request is accepted. Poll `get` afterwards for `CANCELLED`.

```python
payload = run.cancel()
print(payload)
later = run.get()
print(later["status"]["state"])
```

A local `wait` timeout leaves the job running:

```python
try:
    run.wait(timeout=0)
except ns.WaitTimeout as exc:
    print(exc.run_id)
```

## Quiet progress

`examples/quiet_job.py` uses the same recipe as the quickstart and passes `quiet=True` on both `create` and `wait`. Stdout still prints the id and the final state. Other calls on that run show progress again. `create(dry_run=True)` stays silent.

```python
run = job.create(quiet=True)
print(run.id)
record = run.wait(quiet=True)
print(run.id, record["status"]["state"])
```

```bash
python examples/quiet_job.py
```

## Inside an event loop

```python
import asyncio

import nebius_serverless as ns

async def main() -> None:
    job = ns.Job(
        ["nvidia-smi"],
        image="nvidia/cuda:13.1.1-runtime-ubuntu24.04",
        gpu="h100",
        timeout="1h",
    )
    run = await job.create_async()
    record = await run.wait_async()
    print(run.id, record["status"]["state"])

asyncio.run(main())
```

Calling `job.create()` from inside `main` raises `ValidationError` and tells you to use `create_async`.
