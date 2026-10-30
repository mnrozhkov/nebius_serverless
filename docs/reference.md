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
| [Errors](#errors) | Failures raised by this package. |

Constructing a `Job`, loading YAML, or importing the package does not authenticate, upload, or create. The Nebius SDK is imported on the call that resolves a profile or contacts Nebius.

Logs stay on the CLI: `nebius ai job logs <id>`. This package does not stream them.

Synchronous methods are the script API. Inside a running event loop they raise `ValidationError` and name the awaited twin (`create_async`, `get_async`, `wait_async`, `cancel_async`, `jobs.get_async`). Cancelling an await does not cancel the cloud job. Only `cancel` / `cancel_async` does.

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
) -> Run
```

```python
job.create(
    dry_run=True,
    *,
    region=None,
    project=None,
) -> dict
```

`create()` blocks until Nebius has accepted the job and the id is known, then returns a `Run`. It does not wait for the container to finish.

`create(dry_run=True)` builds the request, returns that description, and does not call create. Project and region come from `project=` / `region=` when passed, otherwise from the active SDK profile (`profile=` on the `Job` selects it). A missing or ambiguous project or region raises `ValidationError` before create.

The description includes `image`, `command`, `args` when present, `project`, `region`, `platform`, `preset`, `timeout` (seconds), `pricing`, `subnet_id` when set, `volumes` when set, `env` (key names only), `name`, `disk`, and `shm`. Env values are not included.

`region` is the project region used to resolve a `gpu` alias. Pass it when you already know it and do not want a profile lookup. `project` on this call overrides `Job.project`.

An optional `transport=` keyword replaces the Nebius SDK client. Tests use it. Scripts leave it unset.

### `Job.create_async`

```python
await job.create_async(dry_run=False, *, region=None, project=None)
```

Same call as `create`. Cancelling the await leaves the cloud job running.

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
run.get() -> dict
```

One `nebius ai job get`. Returns the job JSON: state plus the submitted params. Stores that JSON on `record` and `status`.

`FAILED`, `CANCELLED`, `ERROR`, and a platform timeout are data. `get` does not raise because the container exited badly.

### `Run.wait`

```python
run.wait(timeout=None) -> dict
```

Polls `get` about once a second until `status.state` is terminal, then returns that JSON. Terminal states are `COMPLETED`, `FAILED`, `CANCELLED`, and `ERROR`. The raw string is preserved.

`wait(timeout=0)` performs one fetch. When the state is not terminal it raises `WaitTimeout` with the job id. `wait(timeout=seconds)` stops the local poll at that deadline. Neither form cancels the cloud job.

### `Run.cancel`

```python
run.cancel() -> dict
```

Requests cancellation and returns when the request is accepted. The payload does not claim the container has stopped. A later `get` reports the cancelled state when Nebius has finished cancelling.

### Awaited twins

```python
await run.get_async()
await run.wait_async(timeout=None)
await run.cancel_async()
```

Same calls as the synchronous methods. Cancelling `wait_async` or `get_async` does not cancel the cloud job.

## jobs

Module-level collection, `ns.jobs`. It matches the CLI noun `nebius ai job`.

### `jobs.get`

```python
ns.jobs.get(job_id, *, profile=None, project=None) -> Run
```

One `nebius ai job get`, starting from an id string. Returns a `Run` whose `record` is already filled. Does not create a job.

`profile` and `project` select the SDK profile for this fetch. `transport=` is the same test injection as on `Job.create`.

### `jobs.get_async`

```python
await ns.jobs.get_async(job_id, *, profile=None, project=None) -> Run
```

Same fetch as `jobs.get`.

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

| Type | When |
| --- | --- |
| `ValidationError` | Bad command, image, timeout, alias, region, YAML, missing project or region, or a sync call inside a running event loop. |
| `UnsupportedFeature` | Spot on CPU, function YAML, and other commands excluded from this slice. |
| `AccessError` | Authentication or permission failure from the SDK. |
| `CapacityError` | The API rejected the job for quota or capacity. |
| `TransportError` | The call failed and there is no reason to think create was accepted. |
| `SubmissionUncertain` | Create may have been accepted and the id is unknown. The client does not send a second create. |
| `KeyConflict` | The API reports an existing resource and its id is known (`run_id`). |
| `WaitTimeout` | The local wait ended. The cloud job is unchanged. |

Closing the process, a local `WaitTimeout`, and cancelling an awaited twin do not cancel the cloud job.
