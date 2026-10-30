# Replace line counting with batch GPU matrix multiplication

30 October 2026 · Implementation specification · Target repository: `nebius_serverless`

## Goal

Replace `examples/batch/line_count.py` with `examples/batch/matrix_multiply.py`. Demonstrate how a customer runs the same GPU computation for several input sizes using the current `Job.create()` and `Run.wait()` APIs, then retrieves verified results.

Keep `examples/job_quickstart.py` as the minimal nvidia-smi quickstart. Preserve the public SDK API, YAML example, and training example. This change concerns the batch example, its documentation, and its acceptance checks. It introduces no decorators, source-upload feature, result-return API, or batch controller.

This document specifies the replacement for the line-count scenario in `specs/cloud-jobs.md` section 13. Update that section as part of implementation; all other SDK contract requirements remain applicable. Writing this specification does not modify example code or authorize cloud execution by itself.

## Files to change during implementation

| File | Required change |
| --- | --- |
| `examples/batch/matrix_multiply.py` | Add the complete runnable example, replacing the old batch entry point. |
| `examples/batch/line_count.py` | Remove after its replacement and documentation are ready. This is an example migration, not a public API compatibility change. |
| `tests/test_acceptance_offline.py` | Replace the line-count recipe check and add focused behavioral coverage for the new example. |
| `docs/examples.md` | Replace the batch walkthrough, command, prerequisites, and expected output. |
| `specs/cloud-jobs.md` | Update the section 13 introduction and third acceptance scenario to the matrix workload. |
| `specs/implementation-plan.md` | Replace the line-count acceptance step with matrix acceptance. |
| `README.md` | Update batch references only if present; leave the quickstart unchanged. |

Search for additional active line-count references before finishing. Preserve historical documents as history; active run instructions must point to the new example. Do not edit `src/nebius_serverless` to implement this example. Report any genuine SDK blocker separately.

## Customer workflow

The user configures the existing Nebius profile and the example’s bucket and endpoint, then runs:

```bash
uv run python examples/batch/matrix_multiply.py
```

The script submits three independent GPU jobs for matrix sizes `1024`, `2048`, and `4096`, prints each accepted job ID, waits for completion, retrieves each JSON report, and prints a compact results table. All three creates must occur before the first completion wait.

Success means all three jobs completed successfully and all three result objects were read back and validated locally. Job acceptance or successful process exit alone is insufficient. The example permits concurrent execution; it does not guarantee simultaneous starts or a speedup over sequential execution.

## Local example structure

Keep the existing example style: a single Python script with visible configuration constants, a compact embedded `WORKER` string, small helpers where needed, and a guarded `main()` entry point.

Required configuration:

| Setting | Contract |
| --- | --- |
| `SIZES` | `(1024, 2048, 4096)` |
| `GPU` | `"h100"`, resolved through the existing SDK alias |
| `TIMEOUT` | `"1h"`, remote execution deadline |
| Local wait | `run.wait(timeout=5400)`, preserving the existing example’s behavior |
| `IMAGE` | Verified CUDA-enabled PyTorch container pinned by immutable digest; record PyTorch/Python/CUDA versions in docs |
| `BUCKET` | User-configured existing bucket with suitable access |
| `ENDPOINT` | Explicit Object Storage endpoint matching the configured bucket |
| Pricing | Existing on-demand default |

Select and verify a real image during implementation. A placeholder digest or an invented tag cannot satisfy acceptance. Use a prebuilt image with PyTorch installed; no runtime installation and no new local PyTorch dependency for the example controller.

Construct each job with this shape:

```python
ns.Job(
    ["python", "-c", WORKER, prefix, str(size)],
    image=IMAGE,
    gpu=GPU,
    timeout=TIMEOUT,
    volumes=[f"s3://{BUCKET}:/data:rw"],
).create()
```

Use a unique prefix `matrix-multiply/<uuid>/` for each script invocation. Retain `(size, run)` for every accepted job and print the ID immediately. Validate that configured sizes are positive, distinct integers before submitting anything. The supported demonstration is the three listed sizes; arbitrary scaling is not a goal.

No input files are uploaded. Generate matrices remotely. Object Storage is used only to retrieve small result reports. Importing the example must not read credentials, submit work, access storage, or import PyTorch locally.

## Remote computation

Keep the computation in an identifiable `matrix_multiply(size: int)` function inside the embedded worker so the Factory comparison can reuse its logic.

1. Import PyTorch inside the remote worker and require available CUDA. Missing CUDA fails clearly; never fall back to CPU for the main computation.
2. Set random seed `42`. Generate `a` and `b` with shape `(size, size)`, float32 dtype, and `device="cuda"`.
3. Explicitly select a full-float32 matrix multiplication precision policy supported by the pinned PyTorch version. Record the setting; do not rely on a changing default.
4. Under inference/no-gradient execution, perform three warm-up multiplications, followed by ten measured `c = a @ b` repetitions on the same matrices.
5. Use CUDA events and completion synchronization. Report the median multiplication time in milliseconds; exclude allocation, random generation, validation, output reduction, serialization, and remote provisioning.
6. Validate the computation as defined below, calculate `c.mean().item()`, and return the small summary dictionary.
7. Write the validated summary to `/data/<prefix>/<size>.json`, closing the file before successful exit. Keep the matrices remote.

Use the same seed, dtype, precision, warm-ups, repetitions, and validation in every provider comparison. GPU timing is illustrative; this example establishes SDK integration value, not a GPU performance ranking.

## Numerical verification

`verified=true` must represent actual checks:

- Multiply `[[1, 2], [3, 4]]` by `[[5, 6], [7, 8]]` on CUDA and check the known result `[[19, 22], [43, 50]]`.
- Check that the large result has the expected shape and all entries are finite.
- Check nine entries in the large result: the Cartesian product of row and column indices `[0, size // 2, size - 1]`. Compute each reference dot product on CPU in float64 using the actual generated input values. Compare with `rtol=1e-4`, `atol=1e-3`.
- Raise an error if any check fails. A failed computation must not publish a success report.

CPU work here is reference validation only. These checks provide sampled numerical verification, not exhaustive proof of all entries. The random output mean is a visible summary, not the correctness criterion. Do not weaken checks or require exact random means across environments to obtain a pass.

## Result schema and retrieval

Each report is a JSON object with these fields:

| Field | Validation |
| --- | --- |
| `schema_version` | Integer `1` |
| `size` | Integer equal to the requested size; booleans are invalid |
| `gpu` | Nonempty observed CUDA device name |
| `elapsed_ms` | Finite positive number; booleans are invalid |
| `mean` | Finite number; booleans are invalid |
| `verified` | Exactly `true` |

Use strict JSON serialization without NaN or Infinity. Additional reproducibility fields such as PyTorch/CUDA versions and precision policy may be included and documented. The controller supplies the job identity from its retained handle rather than trusting a report to select a job.

After `run.wait(timeout=5400)`, check `run.status == "COMPLETED"`. Only then fetch `s3://<bucket>/<prefix>/<size>.json` through the existing AWS CLI pattern and validate its content. Preserve explicit endpoint selection and subprocess timeouts. Do not introduce boto3 just for this example.

Use a bounded result-availability window of 60 seconds, retrying a missing object at two-second intervals. Each CLI invocation must fit within the remaining overall retrieval deadline. Authentication failures, malformed JSON, and invalid reports fail immediately rather than being retried as publication delays. If reliable missing-object classification is unavailable, fail with an actionable retrieval error instead of retrying every failure indiscriminately.

Collect all three validated summaries and print a table with `size`, `gpu`, `elapsed_ms`, `mean`, and `verified`. Also retain the earlier printed job IDs for troubleshooting. Document sample output as illustrative; do not hardcode timing, means, or GPU names as measured results.

## Failure and resource behavior

Preserve the example’s fail-fast behavior. A submission error, non-success terminal state, wait timeout, failed numerical check, or unavailable/invalid report stops the script with the input size and known job ID in the error message.

Accepted jobs continue after a local failure. State that explicitly in documentation and keep already printed IDs available. There is no automatic resubmission, retry of failed computation, cancellation, or deletion. Explain manual job cleanup and deletion of the invocation’s exact object prefix. Preserve results until the user chooses cleanup.

Separate `Job.timeout` from the local wait and report-retrieval deadline. The example should not claim that a local timeout stops remote execution.

## Offline checks

Use fakes or monkeypatches for cloud/storage operations; offline tests need neither credentials, GPU, network, nor local PyTorch. Exercise behavior rather than only reconstructing a recipe independently of the example.

Required checks:

1. Import has no cloud, subprocess, or local PyTorch side effects; embedded worker source parses.
2. The actual example path submits exactly the configured three jobs with the expected command arguments, image, H100 alias, one-hour timeout, and mount.
3. All creates precede the first wait, and each result is fetched only after successful completion for its matching job.
4. Every invocation uses one fresh prefix shared across its jobs, with distinct result paths for each size.
5. Valid fixture reports produce all three table rows; missing/wrong sizes, booleans as metrics, nonfinite metrics, and false verification fail validation.
6. A failed job is not treated as success and its result is not fetched. A later submission failure does not resubmit earlier jobs.
7. Missing-object handling is bounded; access errors and malformed reports are not retried indefinitely.
8. The existing nvidia-smi/YAML and Axolotl checks remain valid.

Check the numerical verification separately in the selected image with CUDA during live acceptance. Offline fakes establish orchestration behavior, not successful GPU execution.

Run the affected tests and repository-required lint, including `ruff check src tests examples` through `uv`. Follow the repository’s typing, docstring, and line-length conventions. Do not weaken unrelated tests to accommodate this change.

## Documentation and live acceptance

Update the walkthrough with: purpose, configuration, verified image versions, active profile/region/H100 prerequisites, AWS CLI credentials and bucket access, exact run command, expected result shape, timeout semantics, and cleanup instructions. Explain that matrices are created on the GPU and only small JSON summaries are retrieved.

A live validation uses an authorized project and bucket, one script invocation, three one-GPU jobs, and no automatic retries. Reuse existing authorization where it covers this resource envelope; otherwise resolve missing live-run inputs after offline work is ready. A code-only implementation must report live validation as pending.

Record the three job IDs, terminal states, actual GPU names, result object URIs, retrieved JSON, image digest, numerical-check outcome, and cleanup state. Confirm H100 allocation; a different GPU is a mismatch to investigate, not an automatic pass. Numerical tests and final JSON retrieval must pass for every size.

## Definition of done

- The replacement example and active documentation use matrix multiplication; nvidia-smi remains unchanged.
- Three jobs are submitted before waiting, and three valid reports are retrieved and displayed.
- The actual GPU computation passes deterministic and sampled numerical checks.
- PyTorch environment and precision choices are reproducible; there is no local PyTorch prerequisite for the controller.
- Offline checks and required lint pass; live acceptance is separately evidenced or clearly pending.
- No public SDK changes, hidden source upload, function-return API, or batch-controller behavior were introduced.

The `serverless-factory` comparison can consume this worker and example after implementation, using the same workload parameters and result schema for the official Nebius SDK, Modal, and RunPod variants. Its report runner and cross-provider execution remain separate work.
