# Endpoints

30 October 2026. Proposal for discussion. This is the user-interface contract to implement. Nothing in this file is in the package yet. The current jobs surface stays as described in [reference.md](reference.md).

An endpoint is a container that stays up and answers on a managed URL. A job runs a command and finishes. Creating an endpoint allocates the machine until `delete`. Closing the process does not delete it.

Import the package as `ns`. GPU aliases, pricing, volumes, env handling, and the error types are the same as [Job](reference.md#job). `@app.endpoint` in [decorators.md](decorators.md) is this recipe with a Python function as the server.

## Examples

### Serve an image

`command` is optional. Omit it to keep the image entrypoint. Pass a list of strings to override it, with the same quoting rules as `Job`.

```python
import nebius_serverless as ns

endpoint = ns.Endpoint(
    image="vllm/vllm-openai:v0.19.1",
    command=[
        "bash",
        "-c",
        "python3 -m vllm.entrypoints.openai.api_server "
        "--model Qwen/Qwen3-0.6B --host 0.0.0.0 --port 8000",
    ],
    gpu="l40s",
    port=8000,
    auth="token",
    disk="500Gi",
    pricing="spot",
    name="qwen-tiny",
)
print(endpoint.create(dry_run=True))

service = endpoint.create()
print(service.id, service.token)
record = service.wait()
print(service.url, record["status"]["state"])
```

`service.token` is the bearer token Nebius returns on create. A later `endpoints.get` does not have it. `service.url` is the managed `https://` URL. `wait` returns when that URL is present, or when the endpoint has stopped or failed. `RUNNING` means the platform workload is up. It does not mean the model answers yet. Poll the application's own route before sending traffic.

Callers send HTTP themselves. This client does not wrap inference.

```python
import urllib.request

request = urllib.request.Request(
    service.url.rstrip("/") + "/v1/models",
    headers={"Authorization": f"Bearer {service.token}"},
)
with urllib.request.urlopen(request) as response:
    print(response.status)
```

Delete when the endpoint should stop billing:

```python
service.delete()
```

The same recipe as YAML:

```yaml
schema_version: 1
kind: endpoint
image: vllm/vllm-openai:v0.19.1
command:
  - bash
  - -c
  - python3 -m vllm.entrypoints.openai.api_server --model Qwen/Qwen3-0.6B --host 0.0.0.0 --port 8000
gpu: l40s
port: 8000
auth: token
disk: 500Gi
pricing: spot
name: qwen-tiny
```

```python
endpoint = ns.Endpoint.from_yaml("endpoint.yaml")
print(endpoint.create(dry_run=True))
```

### Reload a saved id

`service.id` is the handle. `endpoints.get` performs one get and does not create again. `token` on a reloaded service is `None`.

```python
saved_id = service.id
loaded = ns.endpoints.get(saved_id)
print(loaded.status, loaded.url)
```

### Inside an event loop

```python
service = await endpoint.create_async()
record = await service.wait_async()
await service.delete_async()
```

Calling `endpoint.create()` from inside a running event loop raises `ValidationError` and names `create_async`.

## Contract

| Name | Role |
| --- | --- |
| `Endpoint` | Local recipe. No cloud id. |
| `Service` | One Nebius endpoint after create. |
| `endpoints` | Fetch an endpoint from a saved id. |

Constructing an `Endpoint`, loading YAML, or importing the package does not authenticate, upload, or create. A second `create()` starts another endpoint and returns another `Service`. Each one bills until its own `delete`.

Synchronous methods are the script API. Inside a running event loop they raise `ValidationError` and name the awaited twin (`create_async`, `get_async`, `wait_async`, `delete_async`, `endpoints.get_async`). Cancelling an await does not delete the endpoint. Only `delete` / `delete_async` requests deletion.

This package does not stream endpoint logs. Log access stays on the CLI and the web console.

### `Endpoint`

```python
ns.Endpoint(
    command=None,
    *,
    image,
    port,
    gpu=None,
    platform=None,
    preset=None,
    pricing="on-demand",
    auth="none",
    token=None,
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
| `command` | no | `None` keeps the image entrypoint. A nonempty list of strings overrides it. The first element is the container command. Further elements are POSIX-quoted and joined into the single `args` string. A one-element command omits `args`. A shell string is rejected. |
| `image` | yes | `name:tag` or `registry/path@sha256:<64 hex>`. Sent unchanged. The client does not resolve a tag to a digest. |
| `port` | yes | Container port, an integer from 1 to 65535. One HTTP port. The platform serves it at a managed `https://` URL. gRPC on that same URL is a property of the platform. This client still records one HTTP port. |
| `gpu` | no | Alias from the [alias table](reference.md#gpu-and-cpu-aliases). Omit it for CPU. `gpu="cpu"` raises `ValidationError` and tells you to omit `gpu`. |
| `platform` | no | Explicit platform id. When set, it overrides `gpu`. |
| `preset` | no | Explicit preset id. When omitted, the client sends the minimal preset for the chosen platform. An unknown platform id requires `preset`. |
| `pricing` | no | `"on-demand"` (default) or `"spot"`. `"spot"` is preemptible and follows the current price. `"spot"` on CPU raises `UnsupportedFeature`. Any other value raises `ValidationError`. |
| `auth` | no | `"none"` (default) or `"token"`. `"token"` requires one HTTP port, which this contract already requires. Any other value raises `ValidationError`. |
| `token` | no | Bearer token sent when `auth="token"`. When omitted, Nebius generates one and create copies it onto `Service.token`. The value is left out of dry-run descriptions and exception text. |
| `subnet_id` | no | Sent when set. Omit it when the project has a single subnet. |
| `volumes` | no | Mount strings, passed through, same form as `Job`. |
| `env` | no | `dict[str, str]`. Values are sent on create and left out of dry-run descriptions and exception text. |
| `name` | no | Console label (`metadata.name`). When omitted, the client generates `endpoint-` plus 12 hex characters. It is not a lookup key. |
| `disk` | no | CLI size string, passed through, such as `500Gi`. When omitted, the request uses `250Gi`. |
| `profile` | no | Nebius SDK profile name. When omitted, the active profile is used. |
| `project` | no | Project id. Overrides the profile's project. |

There is no `timeout` parameter. An endpoint has no job deadline. Shared memory follows the job adapter: `16Gi`. It is not a parameter.

After construction these attributes are readable: `command`, `image`, `port`, `gpu`, `platform`, `preset`, `pricing`, `auth`, `token`, `subnet_id`, `volumes`, `env`, `name`, `disk`, `profile`, `project`. `command` is `None` when the image entrypoint is kept. `env` is a tuple of `(key, value)` pairs.

### `Endpoint.from_yaml`

```python
ns.Endpoint.from_yaml(path) -> Endpoint
```

Load a schema-version-1 endpoint document. Relative strings inside the document are not expanded.

Allowed keys: `schema_version`, `kind`, `image`, `command`, `port`, `gpu`, `platform`, `preset`, `pricing`, `auth`, `token`, `subnet_id`, `volumes`, `env`, `name`, `disk`.

`schema_version` must be `1` and `kind` must be `endpoint`. `command` may be omitted. When present it is a list of strings. `port` is an integer. `gpu` may be omitted for CPU. `gpu: cpu` is rejected. Unknown keys, duplicate keys, aliases, anchors, tags, merge keys, and a document over 1 MiB are rejected. `token` and `env` values are accepted and then treated like the Python values: sent on create, omitted from dry-run descriptions and exception text.

### `Endpoint.create`

```python
endpoint.create(dry_run=False, *, region=None, project=None) -> Service
endpoint.create(dry_run=True, *, region=None, project=None) -> dict
```

`create()` blocks until Nebius has accepted the endpoint and the id is known, then returns a `Service`. It does not wait until the URL is ready. Acceptance is not readiness.

`create(dry_run=True)` builds the request, returns that description, and does not call create. Project and region come from `project=` / `region=` when passed, otherwise from the active SDK profile (`profile=` on the `Endpoint` selects it). A missing or ambiguous project or region raises `ValidationError` before create.

The description includes `image`, `command` and `args` when a command was set, `port`, `project`, `region`, `platform`, `preset`, `pricing`, `auth`, `subnet_id` when set, `volumes` when set, `env` (key names only), `name`, `disk`, and `shm`. It does not include env values or the token. When `auth="token"` and `token` was omitted, the description says the token is generated.

`region` resolves a `gpu` alias. `project` on this call overrides `Endpoint.project`.

An optional `transport=` keyword replaces the Nebius SDK client. Tests use it. Scripts leave it unset.

### `Endpoint.create_async`

```python
await endpoint.create_async(dry_run=False, *, region=None, project=None)
```

Same call as `create`. Cancelling the await leaves the endpoint running when create was already accepted.

## Service

One Nebius endpoint id. You get a `Service` from `Endpoint.create()` or `endpoints.get()`. Do not construct it yourself.

Property reads do not perform I/O.

| Property | Meaning |
| --- | --- |
| `id` | Nebius endpoint id. |
| `name` | Display name from the recipe, or from the fetched metadata. Lookup ignores it. |
| `status` | Raw `status.state` string. Before the first successful fetch, this is the state from the create response, or `None` when create did not include one. |
| `record` | Last fetched endpoint JSON, or `None` before the first successful `get` or `wait`. |
| `url` | Managed `https://` URL for the HTTP port, or `None` until a fetch has seen one. |
| `token` | Bearer token from this create call, or `None` on a service loaded by `endpoints.get` and when `auth="none"`. |

### `Service.get`

```python
service.get() -> dict
```

One `nebius ai endpoint get`. Returns the endpoint JSON. Stores that JSON on `record` and `status`, and sets `url` when `status.public_endpoints` contains an `https://` URL. Does not change `token`.

`ERROR` and `STOPPED` are data. `get` does not raise because the workload failed. A missing id raises `Error` and includes that id.

### `Service.wait`

```python
service.wait(timeout=None) -> dict
```

Polls `get` about once a second until the endpoint is ready or will not become ready, then returns that JSON.

Ready means `status.state` is `RUNNING` and `url` is set. `ERROR` and `STOPPED` end the wait as well. The caller reads `service.status` and `service.url`. `PROVISIONING`, `STARTING`, `IMAGE_PULLING`, `STOPPING`, and `DELETING` keep the poll going. `RUNNING` without a URL keeps the poll going.

`wait(timeout=0)` performs one fetch. When the state is not ready and not `ERROR` or `STOPPED`, it raises `WaitTimeout` with the endpoint id. `wait(timeout=seconds)` stops the local poll at that deadline. Neither form deletes the endpoint. The machine keeps billing.

This wait does not request the application's HTTP route. A server that is still loading a model can be `RUNNING` with a URL and still refuse traffic.

### `Service.delete`

```python
service.delete() -> dict
```

Requests deletion and returns when the request is accepted. The payload does not claim the machine has stopped or that billing has ended. A later `get` reports `DELETING` or a missing id once Nebius has finished.

There is no `cancel`. Cancellation is the job verb. An endpoint is removed with `delete`.

### Awaited twins

```python
await service.get_async()
await service.wait_async(timeout=None)
await service.delete_async()
```

Same calls as the synchronous methods. Cancelling `wait_async` or `get_async` does not delete the endpoint.

## endpoints

Module-level collection, `ns.endpoints`. It matches the CLI noun `nebius ai endpoint`.

### `endpoints.get`

```python
ns.endpoints.get(endpoint_id, *, profile=None, project=None) -> Service
```

One `nebius ai endpoint get`, starting from an id string. Returns a `Service` whose `record` is already filled. Does not create an endpoint. `token` is `None`.

`profile` and `project` select the SDK profile for this fetch. `transport=` is the same test injection as on `Endpoint.create`.

### `endpoints.get_async`

```python
await ns.endpoints.get_async(endpoint_id, *, profile=None, project=None) -> Service
```

Same fetch as `endpoints.get`.

## Errors

Every error is an `Error`, the same types as [reference.md](reference.md#errors). Exception text includes the operation and the endpoint id when those are known. The id is stored on `run_id` so existing handlers see a resource id. Text does not include env values, tokens, or registry passwords.

| Type | When |
| --- | --- |
| `ValidationError` | Bad command, image, port, auth, alias, region, YAML, missing project or region, or a sync call inside a running event loop. |
| `UnsupportedFeature` | Spot on CPU, and the excluded shapes in the next section. |
| `AccessError` | Authentication or permission failure from the SDK. |
| `CapacityError` | The API rejected the endpoint for quota or capacity. |
| `TransportError` | The call failed and there is no reason to think create was accepted. |
| `SubmissionUncertain` | Create may have been accepted and the id is unknown. The client does not send a second create. |
| `KeyConflict` | The API reports an existing resource and its id is known. |
| `WaitTimeout` | The local wait ended. The endpoint is unchanged and still bills. |

When `auth="token"`, `token` was omitted, create was accepted, and the response has no token, create raises `Error` with that endpoint id. The caller deletes it and creates again with `token=` set. The client does not invent a replacement token.

Closing the process, a local `WaitTimeout`, and cancelling an awaited twin do not delete the endpoint.

## Out of this proposal

- HTTP helpers, inference clients, and application health probes. The caller uses `service.url`.
- A context manager that deletes on exit. Process death would leave the endpoint billing, and the API has no remote lifetime to enforce.
- More than one port, and TCP or UDP ports.
- `--public` / a public IP. The managed `https://` URL does not need it.
- `stop`, `start`, `restart`, `list`, `delete` of a recipe that was never created, and `get-by-name`.
- Secret references (`--env-secret`, `--token-secret`). A plain `token` string is in this proposal.
- Source upload and Python function serving. Those belong to [decorators.md](decorators.md).
- DevLabs, scaling, and extra replicas. One preset is one machine.

## Names to confirm

This draft uses `Endpoint` for the recipe, `Service` for the cloud id, and `endpoints.get` for the CLI noun `nebius ai endpoint`. `create` and `delete` match `nebius ai endpoint create` and `nebius ai endpoint delete`. `auth` defaults to `"none"`, matching the CLI. `pricing` defaults to `"on-demand"`, matching `Job`.
