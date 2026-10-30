# Nebius Serverless Jobs

Python client for Nebius Serverless AI Jobs.

## Installation

Python 3.10 or later. [uv](https://docs.astral.sh/uv/) installs that interpreter, this package, and the lockfile. From a checkout of this repo:

```bash
uv sync
```

`uv sync` installs this package, the pinned dependencies `nebius==0.6.27` and `PyYAML==6.0.3`, and the locked test and lint tools.

Run the client and the acceptance scripts with `uv run`:

```bash
uv run python
uv run python examples/quickstart.py
uv run python examples/quickstart.py --create
uv run python examples/acceptance/nvidia_smi.py
uv run python examples/acceptance/nvidia_smi.py --create
```

A Nebius CLI profile is required for `create()` and `jobs.get()`. Configure one with [`nebius profile create`](https://docs.nebius.com/cli/configure). The active profile supplies the project id. When that profile does not name a region, `create()` reads it from the project (`spec.region` in the Nebius Python SDK). `profile=`, `project=`, and `region=` select or override them. Constructing a `Job` does not read that profile.

The alias table is in [specs/cloud-jobs.md](specs/cloud-jobs.md). Logs are `nebius ai job logs <id>`. This library does not stream logs.

`examples/quickstart.py` is the recipe below. It dry-runs unless passed `--create`. `--create` submits, waits until the job finishes, and reloads the id. Pass `--region` and `--project` when the profile does not supply them.

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

The same recipe can be loaded from YAML:

```python
job = ns.Job.from_yaml("job.yaml")
run = job.create()
```

`create(dry_run=True)` returns the create request and does not create a job. The acceptance scripts for the short job, the Axolotl fine-tune, and the three line-count jobs dry-run unless they are passed `--create`.

Reference for the classes and methods: [docs/reference.md](docs/reference.md). Worked examples: [docs/examples.md](docs/examples.md).
