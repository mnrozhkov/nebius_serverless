# Nebius Serverless Jobs

Python client for Nebius Serverless AI Jobs.

## Installation

Python 3.10 or later. From a checkout of this repo:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

On Windows, activate with `.venv\Scripts\activate`.

`pip install -e .` installs this package and the pinned dependencies `nebius==0.6.27` and `PyYAML==6.0.3`.

To install the locked test and lint tools as well, from the same checkout:

```bash
uv sync
```

A Nebius CLI profile is required for `create()` and `jobs.get()`. Configure one with [`nebius profile create`](https://docs.nebius.com/cli/configure). The active profile supplies the project id and region. `profile=` and `project=` on `Job` select or override them. Constructing a `Job` does not read that profile.

The alias table is in [specs/cloud-jobs.md](specs/cloud-jobs.md). Logs are `nebius ai job logs <id>`. This library does not stream logs.

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
