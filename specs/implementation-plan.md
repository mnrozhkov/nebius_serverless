# Implementation plan — Cloud Jobs slice

28 October 2026. Work plan for the contract in [cloud-jobs.md](cloud-jobs.md). Do that contract. Where the current tree disagrees with it, the contract wins.

The old offline launcher has been removed. The package currently exports the section 10 errors. This plan adds `Job` and `Run` against Nebius Serverless AI Jobs. It does not edit the YAPF-1739 spec files.

## Outcome

A script installed from this repo can do the quickstart in the contract against a real project, using the caller’s Nebius SDK profile. The same quickstart with `dry_run=True` prints the create request and does not create a job. Unit tests cover validation, alias selection, YAML, the create mapping, and lost-response behavior without credentials and without a GPU.

Live create stays behind the caller’s own profile. The implementation does not embed a project id, token, or registry password. It does not run a billable job unless a later, explicit authorization says to.

## Order

Each step leaves the package importable and the new tests green. Do not start step 2 by wiring a live client into import.

### 1. Public recipe and validation

Add `Job` as a local object. Constructing it validates command, image, timeout bounds, pricing, volumes, and env shape, and does not import the Nebius SDK.

Implement the alias table and region check as pure functions. Region is an argument so tests can pass `eu-north1` or `us-central1` without a profile. `platform=` overrides `gpu`. Unknown explicit platform ids require `preset`.

Implement `Job.from_yaml` for command documents. Reject function documents.

Implement `create(dry_run=True)` so it returns the mapped request once a project, region, and resolved platform are supplied. In tests, pass those in directly. Profile lookup is step 2. Optional `disk` is passed through. Omitted `disk` stays 250 GiB.

Tests: alias rows including B200 and RTX region picks, CPU when `gpu` is omitted, `gpu="cpu"`, timeout at 1 hour and at 1 hour minus one second, tag and digest images, shell-string rejection, quoting of an argument that contains a space, spot on CPU, function YAML, unknown YAML keys.

### 2. Transport seam and Nebius adapter

Put create, get, and cancel behind a small transport object. The default transport is the official Nebius Python SDK (`JobServiceClient` create, operation wait until `resource_id`, get, cancel). Confirm the import path from the installed SDK and pin that version in `pyproject.toml`. Do not shell out to the `nebius` binary and do not hand-roll REST.

A fake transport records the create body and can return an id, drop the id after accept, fail with a transport error before accept, or return a get payload with a chosen `status.state`. Normalization tests use the fake. The default path uses the SDK.

Profile and project resolution uses the SDK’s initialized profile. `profile=` and `project=` select it. Missing project or region fails before create. `dry_run=True` resolves them, builds the request, and does not call create.

Map fields exactly as section 8 of the contract. Send disk 250 GiB and shm 16 GiB. Generate `metadata.name` when `name` is omitted.

`create()` returns a `Run` whose `id` is `resource_id`. If the fake or the SDK says the call may have succeeded and no id came back, raise `SubmissionUncertain` and do not create again.

Tests: request body for the nvidia-smi quickstart, on-demand versus spot flags, env values absent from the raised exception text, lost id, definitive transport failure before accept.

### 3. `Run` and `ns.jobs`

`run.get()` and `ns.jobs.get(id)` call the same get. `wait` polls get until the state is terminal or the local timeout expires. `wait(timeout=0)` is one fetch. `WaitTimeout` does not cancel. `cancel` calls the SDK cancel and returns its acceptance payload. `get` and `wait` return the job JSON for failed and cancelled states without raising.

Preserve the raw `status.state` string on the record.

Tests with the fake transport and a fake clock: non-terminal then terminal, timeout zero, failed state returned, cancel called once, `jobs.get` after a saved id, no second create.

### 4. Package surface

Export `Job`, `jobs`, `Run`, and the section 10 errors from `nebius_serverless`. Remove `submit`, `plan`, `result`, and `refresh` from the public surface.

Decorator modules may remain in the tree during the move. Any public decorator `submit` raises `UnsupportedFeature` with the `Job.create()` direction. Do not register decorators in `__init__.py` as a supported cloud path.

Set `requires-python` to the range the pinned Nebius SDK supports. The old `>=3.12,<3.13` pin belonged to the local launcher, not to this client.

Keep `PyYAML` pinned. Add the Nebius SDK as a required dependency only if it imports cleanly without credentials. If import alone requires a profile, depend on it and still keep `Job()` construction free of that import, and document the extra in the README install line.

Follow the library-practice rules in section 12 of the contract. Public callables are annotated and documented. Ruff stays a dev dependency and `ruff check src tests examples` is clean at the 79-character PEP 8 line.

### 5. Examples and README

Replace the README quickstart with the contract’s script and a `from_yaml` example. State that logs are `nebius ai job logs <id>`. State the alias table by pointing at the spec. Remove the local-backend walkthrough from the first screen.

Add the three scripts in `examples/acceptance/` from section 13 of the contract. They dry-run unless passed `--create`. `nvidia_smi.yaml` is the same recipe as the short job.

Do not rewrite the old offline reports to claim live Nebius evidence.

### 6. Tests

The offline launcher, batch controller, manifest suite, and their reports are already removed. Write the new tests with the fake transport. Do not restore `LocalBackend` or the laptop launcher.

## Acceptance for this plan

Offline, without credentials:

- The quickstart objects construct and `dry_run=True` returns the nvidia-smi request for `eu-north1` and `gpu="h100"`: platform `gpu-h100-sxm`, preset `1gpu-16vcpu-200gb`, timeout 3600 seconds, on-demand, image unchanged.
- The same call with the fake transport returns a `Run.id` and does not call create twice when the id is lost.
- `wait` returns a failed state as data.
- `gpu="b200"` in `me-west1` selects `gpu-b200-sxm-a`. `gpu="h100"` in `us-central1` fails before create.
- `ruff check src tests examples` passes with the PEP 8 selection in `pyproject.toml`.

Live, only after a person authorizes a project, region, and quota. Run each script with `--create`. The `gpu` alias must exist in that region. All three scenarios succeed:

1. `examples/acceptance/nvidia_smi.py --create` reaches `COMPLETED`.
2. `examples/acceptance/axolotl_lora.py --create` reaches `COMPLETED`. The request is the cookbook command: that image, `gpu-h100-sxm`, `1gpu-16vcpu-200gb`, spot, and disk `500Gi`.
3. `examples/acceptance/line_count.py --create` uploads 30 files (10×100, 10×200, 10×300 lines), starts three GPU jobs, and reads back reports `1000`, `2000`, and `3000`. All three states are `COMPLETED`.

Record the job ids. Delete is out of this slice, so cleanup is a manual CLI `nebius ai job delete` noted in the run log, not a library call.

Cancel stays a separate live check, not one of the three scenarios. Cancel one extra job and show that cancel returns before a later get reports the cancelled state.

## Explicitly not in the implementation

Decorators that create jobs, function YAML, secret references, Python log streaming, list/delete/restart/ssh, get-by-name, source snapshot upload, the local launcher as a user path, spot policy ids, and a batch controller.
