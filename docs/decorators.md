# Decorators

30 October 2026. Proposal for discussion. This is the user-interface contract to implement. Nothing in this file is in the package yet. The current jobs surface stays as described in [reference.md](reference.md).

A decorator is a short way to build a [Job](reference.md#job) or an [Endpoint](endpoints.md). It does not add a third kind of cloud object. `@app.job` runs the function once and returns its value. `@app.endpoint` keeps a process up and calls the function on each HTTP request. The two lifetimes stay on two decorators so a reader can see which bill they are starting.

Import the package as `ns`. GPU aliases, images, pricing, and errors match the job and endpoint contracts. Decorating a function does not authenticate, upload, or create.

## Examples

### One function, one job

The function lives in an importable module. `create` uploads that module's directory, starts a job, and returns a `Run`. `result` waits for the job and returns the Python value.

```python
import nebius_serverless as ns

app = ns.App("scores")

@app.job(image="python:3.12-slim", gpu="h100", timeout="1h")
def score(text: str) -> int:
    return len(text)

if __name__ == "__main__":
    print(score.create(dry_run=True, text="hello"))
    run = score.create("hello")
    print(run.id, run.result())
```

`score("hello")` raises `ValidationError` and names `create` and `local`. A direct call does not start a job.

`local` runs the function in this process. It checks the arguments against the signature. It does not check the image, the GPU, or the uploaded files.

```python
print(score.local("hello"))
```

A second `create` starts another job. `options` returns a new binding and leaves `score` unchanged.

```python
run = score.options(timeout="2h", gpu="h200").create("hello")
print(run.result())
```

A function that raises is a failed result, after the job reaches a terminal state:

```python
try:
    run.result()
except ns.RemoteError as exc:
    print(exc.run_id, exc)
```

### One function, one endpoint

`create` returns a `Service` from [endpoints.md](endpoints.md). The process imports the module once, then each `POST` calls the function. Delete the service when it should stop billing.

```python
@app.endpoint(
    image="python:3.12-slim",
    gpu="l40s",
    port=8000,
    auth="token",
)
def predict(text: str) -> dict:
    return {"n": len(text)}

service = predict.create()
record = service.wait()
print(service.url, service.token, record["status"]["state"])
service.delete()
```

The caller posts a JSON object of parameter names:

```python
import json
import urllib.request

body = json.dumps({"text": "hello"}).encode()
request = urllib.request.Request(
    service.url,
    data=body,
    headers={
        "Authorization": f"Bearer {service.token}",
        "Content-Type": "application/json",
    },
    method="POST",
)
with urllib.request.urlopen(request) as response:
    print(json.load(response))
```

A successful response is the JSON return value, here `{"n": 5}`.

### Inside an event loop

```python
run = await score.create_async("hello")
value = await run.result_async()
```

`score.create(...)` inside a running event loop raises `ValidationError` and names `create_async`.

## Contract

| Name | Role |
| --- | --- |
| `App` | Groups functions and holds shared defaults. No cloud id. |
| `@app.job` | A module-level function that creates a `Run`. |
| `@app.endpoint` | A module-level function that creates a `Service`. |
| `Run.result` | Python value from a job started by `@app.job`. |

`App(...)` does not contact Nebius. The cloud call is `create` on the decorated function.

### `App`

```python
ns.App(
    name,
    *,
    source=None,
    image=None,
    gpu=None,
    platform=None,
    preset=None,
    pricing=None,
    timeout=None,
    port=None,
    auth=None,
    token=None,
    subnet_id=None,
    volumes=None,
    env=None,
    disk=None,
    profile=None,
    project=None,
)
```

`name` is a label used in generated console names. It is not a lookup key.

`source` is the directory uploaded on create. When omitted, create uses the directory that contains the function's module file. The upload excludes `.git`, `.venv`, `__pycache__`, and `*.pyc`. Datasets and checkpoints stay on volumes. They are not part of `source`.

Every other parameter is a default for functions on this app. A decorator argument and an `options` argument replace it. Job-only parameters (`timeout`) are rejected on `@app.endpoint`. Endpoint-only parameters (`port`, `auth`, `token`) are rejected on `@app.job`.

### `@app.job`

```python
@app.job(
    image=None,
    gpu=None,
    platform=None,
    preset=None,
    pricing=None,
    timeout=None,
    subnet_id=None,
    volumes=None,
    env=None,
    disk=None,
    name=None,
    profile=None,
    project=None,
)
def function(...): ...
```

`image` and `timeout` are required by the time `create` runs, from this decorator, from `options`, or from the `App`. They follow the `Job` rules: timeout at least 1 hour and at most 168 hours, no clamping.

The decorated object preserves the function name, signature, and annotations for editors. It is not a drop-in callable.

| Call | Effect |
| --- | --- |
| `function(*args, **kwargs)` | Raises `ValidationError` before any cloud call. The message names `create` and `local`. |
| `function.local(*args, **kwargs)` | Binds the signature and calls the function in this process. Returns the value or raises the function's exception. |
| `function.create(*args, dry_run=False, **kwargs)` | Binds the signature, uploads `source`, creates a job, and returns a `Run`. |
| `function.create(*args, dry_run=True, **kwargs)` | Returns the create description and does not upload or create. |
| `function.options(**overrides)` | Returns a new binding. The original function is unchanged. |
| `await function.create_async(...)` | Awaited twin of `create`. |

`create` arguments are the function's arguments. `dry_run`, `region`, `project`, and `transport` are reserved for the create call. A function parameter with one of those names raises `ValidationError` at decoration time.

`options` accepts the same keys as `@app.job`. `region` stays on the create call, as it does for `Job.create`.

The console name defaults to `{app}-{function}-` plus 12 hex characters.

On the wire this is a `Job`. `run.wait()` and `run.get()` behave as they do for a command job. `run.cancel()` cancels that job and does not cancel any other call.

### Arguments and the return value

Arguments and return values are JSON values: `None`, `bool`, `int`, `float`, `str`, `list`, and `dict` with `str` keys. `tuple`, `bytes`, `set`, `NaN`, and `Infinity` raise `ValidationError` before create. The encoded arguments must be at most 1 MiB. A larger return value becomes a `RemoteError` from `result`.

Binding uses the signature before upload. A missing argument, an extra argument, or an unknown keyword raises `ValidationError` and does not create. `*args` and `**kwargs` in the function signature raise `ValidationError` at decoration time.

Dry-run descriptions list the bound parameter names. They omit argument values, env values, and tokens.

### `Run.result`

```python
run.result() -> Any
await run.result_async()
```

Waits until the job is terminal, then returns the function's value.

| Outcome | Result |
| --- | --- |
| The function returned | That value, decoded from JSON. |
| The function raised | `RemoteError` with the exception type name, the message, and `run_id`. |
| The job ended without a result frame | `RemoteError` with `status.state` and `run_id`. |

`result` on a `Run` that was not started by `@app.job` raises `UnsupportedFeature` and tells the caller to use `wait`.

`RemoteError` is an `Error`. Its text includes the operation, the job id, and the remote exception type and message. It does not include env values or tokens.

The runner writes one framed JSON result. `result` reads that frame after the job is terminal. It does not stream logs to the caller.

### `@app.endpoint`

```python
@app.endpoint(
    image=None,
    port=None,
    gpu=None,
    platform=None,
    preset=None,
    pricing=None,
    auth=None,
    token=None,
    subnet_id=None,
    volumes=None,
    env=None,
    disk=None,
    name=None,
    profile=None,
    project=None,
)
def function(...): ...
```

`image` and `port` are required by the time `create` runs. `auth` defaults to `"none"` when neither the decorator, `options`, nor the `App` sets it. The other fields follow [Endpoint](endpoints.md#endpoint). There is no `timeout`.

| Call | Effect |
| --- | --- |
| `function(*args, **kwargs)` | Raises `ValidationError` and names `create` and `local`. |
| `function.local(*args, **kwargs)` | In-process call, same as `@app.job`. |
| `function.create(dry_run=False, *, region=None, project=None)` | Uploads `source`, creates an endpoint, and returns a `Service`. |
| `function.create(dry_run=True, ...)` | Returns the create description. Does not upload or create. |
| `function.options(**overrides)` | Returns a new binding. |
| `await function.create_async(...)` | Awaited twin of `create`. |

`create` takes no function arguments. The function runs later, inside the container, once per HTTP request.

The container imports the module once per process start. Module-level code runs at that import. Each request calls the function again in that process. A new process runs the import again. Spot preemption can replace the process. The client does not restore globals.

One preset is one process. This proposal does not add workers, a queue, or a concurrency limit beyond a single in-process server.

### HTTP

The managed URL accepts `POST` with `Content-Type: application/json`. The body is a JSON object whose keys are the parameter names. When `auth="token"`, the caller sends `Authorization: Bearer <service.token>`.

| Response | Body |
| --- | --- |
| 200 | The return value, encoded as JSON. |
| 400 | `{"error": "<message>"}` when the body is not a JSON object or does not match the signature. |
| 401 | The platform's response when the bearer token is missing or wrong. |
| 500 | `{"error": "<ExceptionName>: <message>"}` when the function raises. |

`GET` is not the function call. A caller who needs a health route probes a path this server does not reserve. `wait` still reports platform `RUNNING` and the managed URL only.

### What may be decorated

The function is defined at module level in a file that Python can import by module name. Decoration rejects a lambda, a nested function, a method, a function in `__main__` with no file, and a notebook cell. `@app.job` and `@app.endpoint` are the outer decorators. The rejection is a `ValidationError` and happens at decoration time, before create.

## Source delivery

`create` makes `source` available at `/workspace` and runs the function from there. The packaged tree must fit the transport the implementation chooses. The endpoint and job file-injection limit of 64 KiB is smaller than a normal module tree, so this contract is not implemented by file injection. An upload that fails before Nebius accepts the resource raises `TransportError` and does not create.

`create(dry_run=True)` shows `source` as the local directory, `function` as `module:qualname`, and the runner command. It lists parameter names for a job call. It does not upload.

The image supplies the Python interpreter and the libraries the function imports. This client does not build an image and does not install the local environment into it.

## Errors

Job and endpoint errors apply unchanged to the cloud call. These are the additions:

| Type | When |
| --- | --- |
| `ValidationError` | A bad function, a signature mismatch, a non-JSON value, a direct call, a reserved parameter name, or a missing `image`, `timeout`, or `port`. |
| `UnsupportedFeature` | `result` on a command `Run`, or a decorator shape this proposal excludes. |
| `RemoteError` | The remote function raised, or a job ended with no result frame. |
| `TransportError` | Source upload failed before create was accepted. |

## Out of this proposal

- `.map()`, fan-out, and a batch controller.
- `.remote()` as a blocking shortcut. The call is `create` plus `result` for a job, and HTTP after `wait` for an endpoint.
- Reusing one warm worker across job calls. Each `@app.job` create starts a new job.
- Notebook definitions and functions that close over local variables.
- Pickle, NumPy arrays, and tensors as argument or return values. Those stay on volumes as files the function reads and writes itself.
- Building an image from the local environment.
- Secret references. Plain `env` and a plain endpoint `token` follow the endpoint and job rules.
- DevLabs, extra replicas, and more than one HTTP port.

## Names to confirm

This draft uses two decorators, `@app.job` and `@app.endpoint`, and `create` as the cloud call, matching `Job.create` and `Endpoint.create`. `local` is the in-process call. `result` is how a job function's value comes back. A direct call raises, so importing a module cannot start a machine.
