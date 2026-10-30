# Reference

User-facing surface of `nebius_serverless`. Import it as `ns`.

```python
import nebius_serverless as ns
```

| Name | Role |
| --- | --- |
| [`Job`](#job) | Local recipe. No cloud id. |
| [`Run`](#run) | One Nebius job after create. |
| [`jobs`](#jobs) | Fetch a job from a saved id. |
| [`configure_logging`](#configure_logging) | Opt in to diagnostic logs. |
| [`diagnostics`](#diagnostics) | Local version and presentation metadata. |
| [Errors](#errors) | Failures raised by this package. |

Constructing a `Job`, loading YAML, or importing the package does not authenticate, upload, or create. The Nebius SDK is imported on the call that resolves a profile or contacts Nebius.

Logs stay on the CLI: `nebius ai job logs <id>`. This package does not stream them.

Synchronous methods are the script API. Inside a running event loop they raise `ValidationError` and name the awaited twin (`create_async`, `get_async`, `wait_async`, `cancel_async`, `jobs.get_async`). Cancelling an await does not cancel the cloud job. Only `cancel` / `cancel_async` does.

## Progress and diagnostics

`create`, `get`, `wait`, `cancel`, and `jobs.get`, plus their awaited twins, print progress on stderr. An interactive terminal shows a Rich spinner. The job id is cyan, an in-progress state is yellow, success is green, and failure is red. The words stay in the line, so color is not the only signal. A notebook, a CI run (`CI`, `GITHUB_ACTIONS`, or `GITLAB_CI`), a pipe, or a dumb terminal gets append-only lines with no color. `NO_COLOR` turns color off and keeps the spinner. `create(dry_run=True)` prints nothing.

`quiet=True` is keyword-only. It suppresses progress for that call only. It is not stored on the `Run`, it does not suppress exceptions or diagnostic logs, and it is not sent to Nebius.

```python
run = job.create()       # submission line
run.wait()               # state, spinner, outcome

run = job.create(quiet=True)
run.wait()               # progress is visible again
run.wait(quiet=True)
```

With debug logging enabled, progress stays append-only so log lines remain readable.

`configure_logging(level="INFO")` sets the `nebius_serverless` logger level. When the application has not already attached a handler, it adds one stderr `StreamHandler` and turns propagation off. Call it again to change the level; the helper keeps a single handler of its own. An application handler is left in place, including its level, filters, and the current propagation setting. Applications that already configure logging should set the `nebius_serverless` logger themselves.

Debug lines can append `event`, `operation_id`, `request_id`, `job_id`, `attempt`, `duration_ms`, and `status_code` when those values exist. `operation_id` identifies the local call. It is not a server request id. Records do not include environment values, credentials, headers, or request bodies.

```python
ns.configure_logging(level="DEBUG")
run.wait(quiet=True)  # no progress; DEBUG records still emit
```

`diagnostics()` returns a JSON-serializable dict and prints nothing:

| Key | Meaning |
| --- | --- |
| `version` | Package version. |
| `python` | Python version. |
| `platform` | OS platform. |
| `presentation` | `plain` or `interactive` for the current stderr. |

It does not report an ambient quiet switch. A call can still pass `quiet=True`. No profile, credentials, environment values, or job records are included.

A local timeout stops waiting only. No cancellation was requested, and the job may still be running. Reload it with `jobs.get(id)` or call `cancel`. Cancelling `wait_async` stops the progress display and does not cancel the cloud job.

SDK progress and these diagnostics are separate from container logs. Those remain `nebius ai job logs <id>`.

## Job

Recipe for one `nebius ai job create`. A second `create()` starts another cloud job and returns another `Run`.

```python
ns.Job(
    command,
    *,
    image,
    gpu=None,
    platform=None,
    preset=None,
    timeout,
    pricing="on-demand",
    subnet_id=None,
    volumes=None,
    env=None,
    name=None,
    disk=None,
    profile=None,
    project=None,
)
```

| Parameter | Required | Meaning |
| --- | --- | --- |
| `command` | yes | Nonempty list of strings. A shell string is rejected. The first element is the container command. Further elements are POSIX-quoted and joined into the single `args` string. A one-element command omits `args`. |
| `image` | yes | `name:tag` or `registry/path@sha256:<64 hex>`. Sent unchanged. The client does not resolve a tag to a digest. |
| `gpu` | no | Alias from the [alias table](#gpu-and-cpu-aliases). Omit it for CPU. `gpu="cpu"` raises `ValidationError` and tells you to omit `gpu`. |
| `platform` | no | Explicit platform id. When set, it overrides `gpu`. |
| `preset` | no | Explicit preset id. When omitted, the client sends the minimal preset for the chosen platform. An unknown platform id requires `preset`. |
| `timeout` | yes | Job deadline: a duration string such as `"1h"`, a number of seconds, or a `timedelta`. Normalized to seconds. Below 1 hour or above 168 hours raises `ValidationError`. Nothing is rounded or clamped. |
| `pricing` | no | `"on-demand"` (default) or `"spot"`. `"spot"` is preemptible and follows the current price. `"spot"` on CPU raises `UnsupportedFeature`. Any other value raises `ValidationError`. |
| `subnet_id` | no | Sent when set. Omit it when the project has a single subnet. |
| `volumes` | no | Mount strings, passed through: `source:container_path[:mode]` or `s3://bucket:/container_path[:mode[:profile]]`. Mode is `ro` or `rw` (default `rw`). The client does not verify the objects. |
| `env` | no | `dict[str, str]`. Values are sent on create and left out of dry-run descriptions and exception text. |
| `name` | no | Console label (`metadata.name`). When omitted, the client generates `job-` plus 12 hex characters. It is not a lookup key. |
| `disk` | no | CLI size string, passed through, such as `500Gi`. When omitted, the request uses `250Gi`. |
| `profile` | no | Nebius SDK profile name. When omitted, the active profile is used. |
| `project` | no | Project id. Overrides the profile's project. |

Shared memory is always `16Gi`. It is not a parameter.

After construction these attributes are readable: `command`, `image`, `gpu`, `platform`, `preset`, `timeout_seconds`, `pricing`, `subnet_id`, `volumes`, `env`, `name`, `disk`, `profile`, `project`. `env` is a tuple of `(key, value)` pairs. `timeout_seconds` is the normalized deadline.

### `Job.from_yaml`

```python
ns.Job.from_yaml(path) -> Job
```

Load a schema-version-1 command document. Relative strings inside the document are not expanded.

```yaml
schema_version: 1
kind: job
image: nvidia/cuda:13.1.1-runtime-ubuntu24.04
command: ["nvidia-smi"]
gpu: h100
timeout: 1h
pricing: on-demand
```

Allowed keys: `schema_version`, `kind`, `image`, `command`, `gpu`, `platform`, `preset`, `timeout`, `pricing`, `subnet_id`, `volumes`, `env`, `name`, `disk`.

`schema_version` must be `1` and `kind` must be `job`. `command` is a list of strings. `gpu` may be omitted for CPU. `gpu: cpu` is rejected. A document whose kind or `execution` is `function` raises `UnsupportedFeature`. Unknown keys, duplicate keys, aliases, anchors, tags, merge keys, and a document over 1 MiB are rejected.

### `Job.create`

```python
job.create(
    dry_run=False,
    *,
    region=None,
    project=None,
    quiet=False,
) -> Run
```

```python
job.create(
    dry_run=True,
    *,
    region=None,
    project=None,
    quiet=False,
) -> dict
```

`create()` blocks until Nebius has accepted the job and the id is known, then returns a `Run`. It does not wait for the container to finish. It prints one submission line. `quiet=True` suppresses that line for this call only. `dry_run=True` stays silent either way.

`create(dry_run=True)` builds the request, returns that description, and does not call create. Project and region come from `project=` / `region=` when passed, otherwise from the active SDK profile (`profile=` on the `Job` selects it). When the project id is known and the profile does not name a region, the region is `spec.region` from IAM v2 `ProjectService.get`. That read is not a job create. A missing or ambiguous project, or a project with no region, raises `ValidationError` before create.

The description includes `image`, `command`, `args` when present, `project`, `region`, `platform`, `preset`, `timeout` (seconds), `pricing`, `subnet_id` when set, `volumes` when set, `env` (key names only), `name`, `disk`, and `shm`. Env values are not included.

`region` is the project region used to resolve a `gpu` alias. Pass it to skip the project lookup. `project` on this call overrides `Job.project`.

An optional `transport=` keyword replaces the Nebius SDK client. Tests use it. Scripts leave it unset.

### `Job.create_async`

```python
await job.create_async(
    dry_run=False,
    *,
    region=None,
    project=None,
    quiet=False,
)
```

Same call as `create`, including `quiet`. Cancelling the await leaves the cloud job running.

## Run

One Nebius job id. You get a `Run` from `Job.create()` or `jobs.get()`. Do not construct it yourself.

Property reads do not perform I/O.

| Property | Meaning |
| --- | --- |
| `id` | Nebius job id. |
| `name` | Display name from the recipe, or from the fetched metadata. Lookup ignores it. |
| `status` | Raw `status.state` string. Before the first successful fetch, this is the state from the create response, or `None` when create did not include one. |
| `record` | Last fetched job JSON, or `None` before the first successful `get` or `wait`. |

### `Run.get`

```python
run.get(*, quiet=False) -> dict
```

One `nebius ai job get`. Returns the job JSON: state plus the submitted params. Stores that JSON on `record` and `status`. Prints one snapshot line. `quiet=True` suppresses it for this call only.

`FAILED`, `CANCELLED`, `ERROR`, and a platform timeout are data. `get` does not raise because the container exited badly.

### `Run.wait`

```python
run.wait(timeout=None, *, quiet=False) -> dict
```

Polls `get` about once a second until `status.state` is terminal, then returns that JSON. Terminal states are `COMPLETED`, `FAILED`, `CANCELLED`, and `ERROR`. The raw string is preserved. The wait prints the observation and one final outcome. `quiet=True` suppresses that progress for this call only.

`wait(timeout=0)` performs one fetch. When the state is not terminal it raises `WaitTimeout` with the job id. `wait(timeout=seconds)` stops the local poll at that deadline. Neither form cancels the cloud job. The job may still be running. Reload it with `jobs.get(id)` or call `cancel`.

### `Run.cancel`

```python
run.cancel(*, quiet=False) -> dict
```

Requests cancellation and returns when the request is accepted. The payload does not claim the container has stopped. Progress says the request was accepted. `quiet=True` suppresses that line for this call only. A later `get` reports the cancelled state when Nebius has finished cancelling.

### Awaited twins

```python
await run.get_async(*, quiet=False)
await run.wait_async(timeout=None, *, quiet=False)
await run.cancel_async(*, quiet=False)
```

Same calls as the synchronous methods, including `quiet`. Cancelling `wait_async` or `get_async` does not cancel the cloud job. Cancelling `wait_async` also stops its progress display.

## jobs

Module-level collection, `ns.jobs`. It matches the CLI noun `nebius ai job`.

### `jobs.get`

```python
ns.jobs.get(job_id, *, profile=None, project=None, quiet=False) -> Run
```

One `nebius ai job get`, starting from an id string. Returns a `Run` whose `record` is already filled. Does not create a job. Prints one snapshot. `quiet=True` suppresses it for this call only.

`profile` and `project` select the SDK profile for this fetch. `transport=` is the same test injection as on `Job.create`.

### `jobs.get_async`

```python
await ns.jobs.get_async(
    job_id,
    *,
    profile=None,
    project=None,
    quiet=False,
) -> Run
```

Same fetch as `jobs.get`, including `quiet`.

## GPU and CPU aliases

`gpu` selects the smallest one-GPU preset on that platform, or the smallest CPU preset when `gpu` is omitted. An alias whose platform is not in the project region raises `ValidationError` before create and names the regions that have it. `platform=` overrides this table.

| `gpu` | Region | Platform | Preset |
| --- | --- | --- | --- |
| `"h100"` | `eu-north1` | `gpu-h100-sxm` | `1gpu-16vcpu-200gb` |
| `"h200"` | `eu-north1`, `eu-north2`, `eu-west1`, `us-central1` | `gpu-h200-sxm` | `1gpu-16vcpu-200gb` |
| `"b300"` | `uk-south1`, `eu-west2`, `us-north1` | `gpu-b300-sxm` | `1gpu-24vcpu-346gb` |
| `"l40s"` | `eu-north1` | `gpu-l40s-a` | `1gpu-8vcpu-32gb` |
| `"b200"` | `us-central1` | `gpu-b200-sxm` | `1gpu-20vcpu-224gb` |
| `"b200"` | `me-west1` | `gpu-b200-sxm-a` | `1gpu-20vcpu-224gb` |
| `"rtx"` | `us-central1` | `gpu-rtx6000` | `1gpu-24vcpu-218gb` |
| `"rtx"` | `uk-south2`, `eu-south1` | `gpu-rtx6000-a` | `1gpu-24vcpu-218gb` |
| omitted | any region string | `cpu-d3` | `2vcpu-8gb` |

The contract copy of this table is [specs/cloud-jobs.md](../specs/cloud-jobs.md).

### `configure_logging`

```python
ns.configure_logging(*, level="INFO") -> None
```

Described under [Progress and diagnostics](#progress-and-diagnostics). `level` is a logging name such as `"DEBUG"` or `"INFO"`, or a numeric level.

### `diagnostics`

```python
ns.diagnostics() -> dict
```

Described under [Progress and diagnostics](#progress-and-diagnostics). Prints nothing and does not contact Nebius.

## Errors

Every error is an `Error`. `UnsupportedFeature` is a `ValidationError`. Exception text includes the operation and the job id when those are known. It does not include env values, tokens, or registry passwords.

| Attribute | Meaning |
| --- | --- |
| `operation` | Call that failed, such as `"create"` or `"wait"`. |
| `run_id` | Job id when it is known. |
| `project` | Project id when it was recorded. |
| `key` | Resource key when it was recorded. |
| `recovery` | Short hint. The default is to reload with `jobs.get` and not to send a second create. |
| `diff` | Optional tuple of extra detail. |
| `code` | Stable SDK category: `validation`, `unsupported`, `access`, `capacity`, `transport`, `submission_uncertain`, `key_conflict`, or `wait_timeout`. |
| `request_id` | Server request id when the Nebius exception already exposed one. Otherwise `None`. |

| Type | When |
| --- | --- |
| `ValidationError` | Bad command, image, timeout, alias, region, YAML, missing project or region, or a sync call inside a running event loop. |
| `UnsupportedFeature` | Spot on CPU, function YAML, and other commands excluded from this slice. |
| `AccessError` | Authentication or permission failure from the SDK. |
| `CapacityError` | The API rejected the job for quota or capacity. |
| `TransportError` | The call failed and there is no reason to think create was accepted. |
| `SubmissionUncertain` | The outcome of create is unknown. The client does not send a second create. |
| `KeyConflict` | The API reports an existing resource and its id is known (`run_id`). Reload that job. Do not send a second create. |
| `WaitTimeout` | Local waiting stopped. No cancellation was requested. The job may still be running. |

Closing the process, a local `WaitTimeout`, and cancelling an awaited twin do not cancel the cloud job.
