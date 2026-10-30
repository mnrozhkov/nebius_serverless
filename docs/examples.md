# Examples

Scripts below use the active Nebius profile. `create(dry_run=True)` prints the request and does not create a job. Pass a real `create()` only when the project, region, and quota are authorized.

The alias for `gpu` must exist in that region. See the [alias table](reference.md#gpu-and-cpu-aliases). Logs are `nebius ai job logs <id>`.

`examples/quickstart.py` is the README recipe. Acceptance scripts live in `examples/acceptance/`. Each dry-runs unless passed `--create`.

## README quickstart

One on-demand H100 job. In `eu-north1`, `gpu="h100"` selects `gpu-h100-sxm` and `1gpu-16vcpu-200gb`. Omit `gpu` for a CPU machine (`cpu-d3`, `2vcpu-8gb`). `pricing="spot"` on that machine raises `UnsupportedFeature`.

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

```bash
python examples/quickstart.py
python examples/quickstart.py --create
```

`--create` waits until `status.state` is `COMPLETED`, then reloads the id. Pass `--region` and `--project` when the profile does not supply them.

## Short job

The cookbook first job. `gpu="l40s"` is that machine: in `eu-north1` it selects `gpu-l40s-a` and `1gpu-8vcpu-32gb`. The cookbook uses a 15-minute timeout. This client sends `1h`, the API minimum, and does not clamp `15m` up.

```python
import nebius_serverless as ns

job = ns.Job(
    ["bash", "-c", "nvidia-smi"],
    image="nvidia/cuda:13.1.1-runtime-ubuntu24.04",
    gpu="l40s",
    timeout="1h",
    name="my-job",
)
print(job.create(dry_run=True))

run = job.create()
print(run.id)
record = run.wait()
print(record["status"]["state"])
```

The same recipe as YAML, `examples/acceptance/nvidia_smi.yaml`:

```yaml
schema_version: 1
kind: job
image: nvidia/cuda:13.1.1-runtime-ubuntu24.04
command: ["bash", "-c", "nvidia-smi"]
gpu: l40s
timeout: 1h
name: my-job
```

```python
from_yaml = ns.Job.from_yaml("examples/acceptance/nvidia_smi.yaml")
print(from_yaml.create(dry_run=True))
```

With a profile and an explicit region, both descriptions match.

```bash
python examples/acceptance/nvidia_smi.py
python examples/acceptance/nvidia_smi.py --create --profile my-profile --project project-id
```

`--create` waits until `status.state` is `COMPLETED`.

## Spot job with a larger disk

One spot GPU job. The full cookbook command is `examples/acceptance/axolotl_lora.py`. In `eu-north1`, `gpu="h100"` selects `gpu-h100-sxm` and `1gpu-16vcpu-200gb`. Shared memory stays the `16Gi` default. The published command does not mount a volume.

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
python examples/acceptance/axolotl_lora.py
python examples/acceptance/axolotl_lora.py --create
```

## Three jobs over one bucket

Three `Job.create()` calls. There is no `.map()`. The script `examples/acceptance/line_count.py` writes 30 files, uploads them when `--create` is set, and reads back reports `1000`, `2000`, and `3000`.

Dry-run does not upload:

```bash
python examples/acceptance/line_count.py --gpu h100
```

`--create` needs `ACCEPTANCE_BUCKET` and uses `NEBIUS_REGION` (default `eu-north1`) only for the Object Storage endpoint. The library does not delete the jobs. Cleanup is `nebius ai job delete <id>`.

```python
import os

import nebius_serverless as ns

bucket = os.environ["ACCEPTANCE_BUCKET"]
prefix = "acceptance/example"
shards = ("shard-0", "shard-1", "shard-2")
jobs = [
    ns.Job(
        ["python", "-c", "print('count')", prefix, shard],
        image="python:3.12-slim",
        gpu="h100",
        timeout="1h",
        name=f"line-count-{shard}",
        volumes=[f"s3://{bucket}:/data:rw"],
    )
    for shard in shards
]
for job in jobs:
    print(job.create(dry_run=True))

runs = [job.create() for job in jobs]
for run in runs:
    record = run.wait(timeout=5400)
    print(run.id, record["status"]["state"])
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
