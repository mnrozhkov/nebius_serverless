# Nebius Serverless Jobs

Python client for Nebius Serverless AI Jobs.

## Installation

Python 3.10 or later. [uv](https://docs.astral.sh/uv/) installs that interpreter, this package, and the lockfile. From a checkout of this repo:

```bash
uv sync
```

`uv sync` installs this package, the pinned dependencies `nebius==0.6.27`, `PyYAML==6.0.3`, and `rich==15.0.0`, and the locked test and lint tools.

Run the client and the example scripts with `uv run`:

```bash
uv run python
uv run python examples/job_quickstart.py
uv run python examples/from_yaml/nvidia_smi_yaml.py --config examples/from_yaml/nvidia_smi.yaml
```

A Nebius CLI profile is required for `create()` and `jobs.get()`. Configure one with [`nebius profile create`](https://docs.nebius.com/cli/configure). The active profile supplies the project id. When that profile does not name a region, `create()` reads it from the project (`spec.region` in the Nebius Python SDK). `profile=`, `project=`, and `region=` on `Job` select or override them. Constructing a `Job` does not read that profile.

The alias table is in [specs/cloud-jobs.md](specs/cloud-jobs.md). Logs are `nebius ai job logs <id>`. This library does not stream logs.

`create()`, `get()`, `wait()`, and `cancel()` print progress on stderr. `quiet=True` suppresses progress for that call only. `ns.configure_logging()` turns diagnostics on separately, and `ns.diagnostics()` returns local metadata, including whether stderr is `plain` or `interactive`. A local timeout does not cancel the remote job.

`examples/job_quickstart.py` is the recipe below. `examples/from_yaml/nvidia_smi_yaml.py --config` loads a recipe from YAML. The other example settings live in the Python file.

```python
import nebius_serverless as ns

job = ns.Job(
    ["nvidia-smi"],
    image="nvidia/cuda:13.1.1-runtime-ubuntu24.04",
    gpu="h100",
    timeout="1h",
)
run = job.create()
print(run.id)
record = run.get()
record = run.wait()
run.cancel()
run = ns.jobs.get(saved_id)
```

`examples/quiet_job.py` passes `quiet=True` on both `create` and `wait`. Stdout still prints the id and the final state:

```python
run = job.create(quiet=True)
print(run.id)
record = run.wait(quiet=True)
print(run.id, record["status"]["state"])
```

The same recipe can be loaded from YAML:

```python
job = ns.Job.from_yaml("job.yaml")
run = job.create()
```

`create(dry_run=True)` returns the create request and does not create a job. The example scripts call `create()` and use the active profile.

Reference for the classes and methods: [docs/reference.md](docs/reference.md). Worked examples: [docs/examples.md](docs/examples.md).
