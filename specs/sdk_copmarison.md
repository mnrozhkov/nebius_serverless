# Python SDK example comparison design

30 October 2026 · Proposal for the development team · No implementation changes

Show how the designed Nebius SDK reduces the work between a developer’s intent and a verified cloud result. Use two concrete tasks: run `nvidia-smi`, then submit three GPU matrix multiplications and collect verified results. Lead with an equivalent Nebius Python SDK before and after comparison; use Modal and RunPod to show the competitive developer experience.

The customer value proposition is: **Run existing workloads on Nebius with less integration work, and reuse that simpler workflow when processing more inputs.** The examples must demonstrate this value through equivalent successful outcomes, visibly removed customer responsibilities, and reproducible measurements.

Fewer lines are supporting evidence. Lead with what customers can accomplish and which work they no longer have to do. Measure onboarding time separately to establish whether the reduced integration work translates into faster first results.

## Customer value to prove

The primary audience is the development team, but the unit of value is the customer’s task. Every highlighted API improvement must answer: “What does this save the customer from learning, writing, debugging, or maintaining?”

| Customer need | Work exposed in the official SDK example | Designed SDK experience to demonstrate | Evidence to show |
| --- | --- | --- | --- |
| Run my existing command on a GPU. | Construct nested API requests and specify platform details. | Express command, image, GPU choice, and deadline through `Job`. | Same resolved Nebius request settings and successful command; highlight the configuration and request-building code removed from the caller. |
| Know whether my work finished successfully. | Fetch state repeatedly, recognize terminal states, and manage the polling interval. | Call `run.wait()` and explicitly check success. | Same success/failure decisions; show the polling loop moving out of customer code. |
| Run several GPU computations without rebuilding cloud integration. | Apply request construction and lifecycle handling to each execution. | Reuse the `Job` and `Run` pattern with the same PyTorch worker. | Three independently identified computations at sizes 1,024, 2,048, and 4,096; verified result summaries and fewer orchestration lines. |
| Adapt the example to my workload. | Find which API request fields correspond to the intended change. | Change the command, image, or documented resource option at the authoring surface. | A small follow-up edit task: inspect changed lines and verify the new result; measure time and mistakes. |

The first three rows can establish concrete integration savings through code inspection and execution. The fourth tests whether the abstraction helps beyond copying the supplied example. Reduced maintenance burden is supported by less caller-owned orchestration; fewer production incidents would require separate evidence.

### Evidence required for each value claim

Present each example as **customer task → before friction → after workflow → verified result → quantified saving**.

1. **Equivalent outcome:** demonstrate that the shorter version still performs the required work. An accepted job ID alone is insufficient.
2. **Removed responsibility:** mark exactly which caller-owned code disappears and which library operation replaces it. Moving code into an uncounted example helper does not establish a saving.
3. **Measured size:** report both orchestration and whole-example reductions. Explain remaining setup and data code beside the numbers.
4. **Observed effort:** time a first run and a small adaptation task to support claims about onboarding and time to value.

The main before and after pair proves improvement over the existing Nebius integration path. Modal and RunPod establish the competitive benchmark and remaining opportunities; the customer-value case does not depend on being shorter than every competitor.

## Scope and baseline

Use the current implementation in `/Users/mnrozhkov/dev/nebius_serverless` as the main “after” baseline. Its public workflow is `ns.Job(...).create()`, followed by `run.wait()` and a status check. The cloud Jobs contract supersedes older sketches using `.submit()`, `.result()`, decorators, and automatic source delivery.

| Baseline | Role in the comparison |
| --- | --- |
| `examples/job_quickstart.py` | Starting point for the simple example; currently mixes first-run and lifecycle operations. |
| `examples/batch/matrix_multiply.py` | Selected batch showcase: three GPU matrix sizes. Replaces line counting in the comparison design. |
| `specs/cloud-jobs.md` | Authority for supported APIs and execution behavior. |
| `nebius==0.6.27` | Official SDK version pinned by the implementation at inspection time. |
| Modal documentation | Function authoring, execution, and parallel mapping reference. |
| RunPod endpoint SDK and new app SDK | Distinguish an already-deployed endpoint from authoring and deploying a function. |

Freeze source snapshots and record their hashes when implementing the comparison. The workspace examples are changing; do not compare counts from different revisions. The separate Python drafts already in this directory are incomplete exploratory material, not an approved or validated comparison suite. Older line-count snapshots are historical and sit outside the selected showcase.

## How to present the examples

Use a short review document or six presentation panels. Keep the before and after examples adjacent, with the same task and success condition above both.

| Panel | What to show | What the team should learn |
| --- | --- | --- |
| 1. Customer value | “Run your existing command with less cloud integration work.” State the two tasks and their success conditions. | Establish the customer benefit that the following examples must prove. |
| 2. Simple before and after | Official Nebius SDK beside designed SDK; highlight request construction, resource selection, and polling. Add matching success evidence and measured code reduction. | Show which work the customer no longer writes or maintains. |
| 3. Simple competitor comparison | Modal, RunPod app SDK, and RunPod endpoint client plus its required worker setup. | Compare the first-run experience without hiding deployment work. |
| 4. Batch before and after | Same three matrix sizes and verified result summaries. Highlight the submission and completion sections; show a result table and both code-count reductions below. | Prove that the simpler integration carries through to a multi-input workflow without rewriting workload logic. |
| 5. Batch competitor comparison | Equivalent outputs through Modal mapping and RunPod submission. Include result-retrieval and execution-model differences. | Show where competitors offer stronger function and collection abstractions. |
| 6. Product implications | Current improvements, remaining friction, proposed example changes, and onboarding measures. | Connect evidence to the next development priorities. |

Each example should have four elements: the task, the visible code, the setup required before running it, and the observable success result. Put full source in an appendix or linked files; presentation excerpts must identify what they omit.

End each before and after panel with a short evidence statement, populated only after validation:

> Same verified outcome. Customer-owned orchestration reduced from [B] to [A] lines ([R]%). The customer no longer writes [specific responsibilities]. [Remaining setup] is still required.

When onboarding observations are available, add a separate statement with the sample size and measured time to result. Keep a blank measurement out of the final presentation rather than replacing it with an estimated marketing claim.

Use annotations such as “SDK builds the request” and “SDK polls the job.” Avoid labeling a shorter snippet “simpler” without explaining what the developer no longer needs to understand or maintain.

## Simple example contract

**Task:** execute `nvidia-smi` remotely on a requested H100 and confirm successful completion.

For the two Nebius variants, preserve the same image, command, region, machine preset, remote deadline, and relevant disk defaults. Both must submit, expose a job ID, wait for completion, and reject an unsuccessful terminal state. Authentication and project selection must be documented for both.

The proposed main “after” excerpt is:

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
run.wait()
if run.status != "COMPLETED":
    raise RuntimeError(f"{run.id}: {run.status}")
```

This is proposed presentation code using the current API, not a change to the example. Retain a normal `main()` wrapper in the eventual runnable file. Count that wrapper in full-file totals for every implementation that uses one.

The official SDK version should use its supported synchronous interface. Do not introduce `asyncio` merely to make the baseline longer. Show the actual typed create request and the caller-owned polling loop, including SDK cleanup. The designed SDK owns these details internally; it does not remove their implementation cost from the product.

Successful status and visible command output are different milestones. The current Nebius SDK example does not return stdout. Give `nebius ai job logs <id>` as a separate step if the demo includes inspecting the GPU output. Include that step when comparing time to visible output against a competitor returning a Python string.

### Recommended quickstart changes

Give this example the customer-facing purpose “My first successful GPU command.” Its proof is a verified command execution with visibly less integration code. The diagnostic command demonstrates access to remote compute; it does not itself establish model inference or training value.

| Recommendation | Reason |
| --- | --- |
| Keep create, print ID, wait, and check status in the main journey. | The reader reaches one unambiguous success condition. `wait()` alone also returns on failure. |
| Move `get()`, reattachment, and cancellation into a separate lifecycle recipe. | These are useful follow-up tasks but distract from the first successful run. |
| Remove cancellation after the completion wait from the main quickstart. | It does not illustrate stopping active work. A cancellation recipe should use a still-running job. |
| Print a compact completion message instead of two full records. | Make the outcome easy to spot; keep full metadata inspection in the lifecycle recipe. |
| State the profile, project, region, quota, and subnet prerequisites beside the run command. | A short Python file does not eliminate platform setup. |
| Explain `Job.timeout` versus `Run.wait(timeout=...)`. | The former limits remote execution; the latter stops local waiting without cancelling the job. |

## Batch GPU matrix multiplication contract

**Customer task:** “Run my GPU computation for several input sizes and collect results without writing cloud orchestration from scratch.”

Submit three independent matrix multiplications with `sizes = [1024, 2048, 4096]`. Each worker creates two square matrices on CUDA, computes `c = a @ b`, validates the result, and produces a small JSON-compatible summary. Generate matrices remotely; uploading input files is no longer part of this example.

Use the same worker logic across the official Nebius SDK, designed Nebius SDK, Modal, and RunPod. Keep a fixed random seed, float32 dtype, precision policy, warm-up count, and measurement repeat count. Pin the PyTorch environment when implementing the examples; use the same image for the two Nebius variants. Request one H100 per execution where supported and record the actual GPU. There is no CPU fallback: missing CUDA should fail clearly.

Submit all three jobs before waiting for their results, or use a platform collection API with parallel execution semantics. This permits overlap; it does not guarantee simultaneous execution or three allocated GPUs. Modal and RunPod workers may process more than one input over their lifetime, whereas each Nebius submission creates a fresh Job.

### Shared workload and result

Use the familiar `matrix_multiply(size: int)` function as the workload boundary. Import PyTorch inside the worker. Keep platform submission and output transport outside the computation so the same algorithm remains recognizable in all variants.

The result contract is:

| Field | Meaning |
| --- | --- |
| `size` | Requested square matrix dimension. |
| `gpu` | Observed CUDA device name. |
| `elapsed_ms` | Median GPU multiplication time after warm-up; excludes matrix generation, validation, result serialization, and provisioning. |
| `mean` | Mean of the computed output, for an engaging visible summary; not a correctness assertion. |
| `verified` | True only after the specified numerical checks pass; otherwise fail the execution. |

Attach execution identity locally when collecting summaries. Keep matrices on the worker; returning a large tensor would introduce an unrelated serialization and transfer problem.

**Validation:** include a small deterministic multiplication with a known answer, plus a sampled check of the actual random multiplication against CPU reference calculations. Fix the sampled positions and numerical tolerances in the shared worker and use them unchanged across providers. `verified` means these checks passed, not an exhaustive proof of every output element. Validate result shape and finiteness as well. Do not compare exact random means across different runtimes as a correctness criterion.

**Timing:** use CUDA events with completion synchronization, warm up first, and report a median over a fixed number of repetitions. CUDA work is asynchronous, so an unsynchronized host timer is unsuitable. Keep the GPU measurement separate from submission-to-result elapsed time. [PyTorch CUDA execution semantics](https://docs.pytorch.org/docs/2.15/notes/cuda.html).

This is a developer-experience demonstration, not a GPU performance ranking. A faster matrix multiplication does not prove a better SDK. The measurable SDK value is less integration work to reach the same verified result.

### Show the workflow in four stages

| Stage | Shared responsibility | Comparison focus |
| --- | --- | --- |
| Prepare | Choose three sizes and a compatible PyTorch environment. | Environment setup and worker delivery are visible. |
| Submit | Send three computations and retain size-to-execution identity. | Typed requests versus `Job` recipes versus remote functions. |
| Observe | Wait for each execution and distinguish failure from success. | Caller polling versus handles or function results. |
| Collect and verify | Retrieve summaries and validate size, GPU, finite metrics, and verification status. | Demonstrate useful results beyond an accepted submission. |

For the Nebius before and after pair, keep the computation, image, output mechanism, and validation identical. Replace only SDK setup, request construction, submission, and polling. This isolates the value of the designed SDK.

### Result retrieval across platforms

The primary success condition is three verified summaries available to the local caller. Durable storage is not an additional requirement for competitors that can return those summaries directly.

For the current Nebius Jobs API, plan to write one JSON summary per job into a uniquely named prefix on a configured object-storage mount, then read it locally after successful completion. Show and count this storage setup and retrieval code in both Nebius variants. A mounted local file alone is insufficient; verify that the caller can retrieve the remote object. Do not imply that `run.wait()` returns the Python result.

For Modal and RunPod function APIs, use their supported result-return mechanism. Count the function wrapper and invocation code. This deliberately exposes a customer-experience difference: the current Nebius command interface needs an explicit output path, while a function interface can return a small value. A future Nebius decorator/result API may address that difference, but belongs in the proposed-design panel.

### Recommended batch example changes

| Recommendation | Customer value or proof |
| --- | --- |
| Replace line counting in the showcase with matrix multiplication. | The demonstration visibly exercises the GPU using familiar Python computation. |
| Use three fixed sizes and one shared worker. | Customers see how a single workload becomes a small batch through parameter changes. |
| Keep all completion waits after submission. | Preserve opportunities for concurrent remote execution. |
| Use a pinned PyTorch image and explicit worker delivery. | Count the environment and packaging work the customer actually needs. The current Nebius slice has no automatic source upload. |
| For the first command implementation, pass the compact worker explicitly as command code, if practical. | Avoid adding an unimplemented source-delivery feature. If an image build is needed, show and count its files and steps. |
| Collect small summaries and show one result table. | Make successful GPU execution and result retrieval immediately visible. |
| Keep numerical verification in the shared worker. | Shorter orchestration must still deliver checked computation. |
| Document fail-fast behavior and retained remote jobs. | A failed caller does not automatically cancel already accepted Nebius Jobs. |
| Keep partial failure and retry in a later companion example. | Recovery needs its own identity and execution contract. |

The final display should have one row per size, with GPU name, multiplication milliseconds, output mean, and verification status. Use observed values only. Put SDK code savings beside this table; keep GPU timing visually separate from onboarding measurements.

Do not claim bounded concurrency, automatic retries, durable controller recovery, or exactly-once processing for the current loop. Three submissions bound this demonstration’s job count, not the SDK’s general concurrency behavior.

## Competitor comparison rules

| Variant | Include in visible authoring scope | Setup that must remain visible |
| --- | --- | --- |
| Nebius official SDK | Typed request, service client, operation acceptance, job polling, result verification. | Profile, project, permitted region/preset, image, storage access. |
| Designed Nebius SDK | `Job`, `create`, execution handle, status check, result verification. | Same Nebius prerequisites; alias/default resolution moves into the SDK. |
| Modal | App, function, environment, invocation or mapping, result collection. | Authentication, remote dependencies, storage and secrets; execution via Modal CLI. |
| RunPod endpoint SDK | Client **and** worker handler; include packaging separately. | Worker deployment, endpoint ID, GPU configuration, API authentication, storage credentials. |
| RunPod app SDK beta | App, decorated function, invocation, storage configuration. | Version requirement, authentication, development/deployment command, secrets. |

RunPod’s current documentation introduces `runpod.App`, `@app.queue`, and `@app.task`; it identifies the new surface as beta and directs users to `2.0.0rc1` until 2.0 is released. Include it as a separately labeled track. Comparing only a manually deployed RunPod worker would omit its newer authoring experience. [RunPod SDK overview](https://docs.runpod.io/sdk/overview), [quickstart](https://docs.runpod.io/sdk/quickstart).

The established endpoint client submits inputs to an existing service. Its short caller code cannot represent the whole first-run journey. [RunPod endpoint operations](https://docs.runpod.io/serverless/endpoints/operation-reference).

Modal functions use an autoscaling container pool, and `.map()` or `.starmap()` provides parallel invocation. These are useful competitive capabilities, but they are not the same lifetime model as a fresh Nebius Job per submission. [Modal scaling and parallel execution](https://modal.com/docs/guide/scale).

Use two explicit lenses: **same Nebius behavior** for the before and after comparison; **same user outcome** for cross-platform comparisons. Hardware labels, storage paths, deployment behavior, output retention, and deadline semantics may differ across providers. Do not collapse those differences into one “winner” score.

## Measuring lines and complexity

Publish counts only after complete equivalent examples exist and have been reviewed. Do not use the incomplete drafts as benchmark results.

| Measure | Definition |
| --- | --- |
| Whole-example Python lines | Nonblank, non-comment physical lines across all required client, worker, and helper files; exclude docstrings. Include embedded worker code and delimiter lines under one documented counting rule. |
| Orchestration lines | The marked sections for SDK initialization, remote configuration, submission, waiting, status handling, and client cleanup. Include imports used by those sections. |
| Shared workload and data lines | Worker logic, matrix generation, result transport, and validation. Report separately, but include in the whole-example total. |
| Non-Python setup | Dockerfile/config lines and manual setup steps, listed separately rather than assigned zero cost. |
| Concepts exposed | Concrete objects and decisions the developer encounters, such as request/spec/operation/state polling or app/function/invocation. List names; avoid subjective numerical complexity ratings. |
| Interfaces crossed | Python, CLI, console, image registry, and storage setup required for the selected journey. |

Apply consistent formatting. Do not compress the “after” code into one-liners while spreading the baseline across many lines. Standard-library helpers are allowed; bespoke wrappers count wherever their implementation lives. A pre-existing platform SDK’s internals do not count as user code on either side.

Calculate reduction as `(before − after) / before × 100`, separately for orchestration and whole-example lines. Label the denominator. A large orchestration reduction can coexist with a modest whole-example reduction when data handling dominates.

Proposed results table:

| Task and variant | Python total | Orchestration | Workload and data | Other setup | Verified outcome |
| --- | --- | --- | --- | --- | --- |
| Quickstart — official Nebius | Pending | Pending | Pending | Enumerated steps | Pending |
| Quickstart — designed Nebius | Pending | Pending | Pending | Enumerated steps | Pending |
| Quickstart — Modal / RunPod variants | One row each | One row each | One row each | Enumerated steps | Pending |
| Batch — same variants | One row each | One row each | One row each | Enumerated steps | Pending |

## Demonstrating onboarding and time to value

Measure two starting points separately: a new developer with an account but no local configuration, and a developer with credentials and storage already configured. Include account approval and quota delays as separate elapsed-time components when they occur.

Record time to accepted execution, time to confirmed success, and time to a verified useful result. For quickstart, the useful result is visible `nvidia-smi` output. For batch, it is three retrieved matrix result summaries with numerical checks passed. Also record documentation lookups, setup mistakes, failed attempts, and assistance required.

After the first successful run, ask the participant to make one equivalent change in both Nebius variants: change the command to a supplied diagnostic command, or add a fourth matrix size, such as 3,072, using the same verification contract. Record changed lines, completion time, mistakes, and assistance. This tests whether the example becomes a useful starting point for customer work.

Separate hands-on setup time from cloud provisioning, image preparation, execution, and result retrieval. Rotate example order across participants to reduce learning effects. Report the participant count and observed spread; do not promise a percentage improvement before collecting observations.

The intended development-team message is: “The SDK owns routine cloud orchestration, so developers can spend more of their first session expressing and verifying their workload.” Evidence should identify both removed work and remaining blockers.

## Current value and future design

The current SDK can demonstrate concise command submission, readable GPU aliases and deadlines, execution handles, and built-in polling. The batch example can demonstrate how those conveniences apply repeatedly without changing existing workload code.

Function decorators, source packaging, Python return values, and collection execution belong in a separately labeled future-design panel. They are not supported by the current cloud Jobs slice. If shown later, use one specific user problem per proposal: avoiding embedded command strings, delivering local code, retrieving a typed result, or handling partial batch failures.

Do not invent an implemented Nebius `.map()` to match Modal. First define ordering, admission limits, failure reporting, cancellation, retries, and recovery. The competitor comparison should inform that design rather than disguise the gap.

## Deliverables and acceptance for the next stage

The next stage would produce two reviewed Nebius before and after pairs, equivalent Modal and RunPod examples, a setup guide, reproducible line-count results, and the six-panel narrative. Keep lifecycle and failure-recovery recipes separate from the primary comparison.

Before presenting numerical claims, check:

1. Both Nebius versions run the same command and matrix workload/result contract with equivalent resource settings.
2. Every platform shows all required author-owned code and setup, including worker deployment when applicable.
3. All examples check the intended success condition; none treats submission acceptance as completion.
4. Full-file and excerpt counts reconcile, with shared helpers counted transparently.
5. Syntax checks, local fixture checks, API inspection, and live execution are reported as distinct validation levels.
6. Any future API is labeled proposed, and onboarding speed claims have measured evidence.
7. Each headline benefit names a customer responsibility removed and links it to the before and after code and verified output.
8. All three matrix summaries are retrieved, associated with their requested sizes, and numerically checked; output transport is included in the comparison scope.
9. The final presentation answers both “Does it still accomplish my task?” and “What effort does it save me?” without requiring the presenter to explain missing evidence.

Existing source examples and SDK implementation remain unchanged during this design stage.

## References

- [Nebius Python SDK](https://github.com/nebius/pysdk) — official SDK and supported sync/async usage.
- [Nebius Jobs quickstart](https://docs.nebius.com/serverless/quickstart/jobs) — job creation, operation acceptance, status and log workflow.
- [Current cloud Jobs contract](/Users/mnrozhkov/dev/nebius_serverless/specs/cloud-jobs.md) — supported designed SDK surface.
- [Current quickstart](/Users/mnrozhkov/dev/nebius_serverless/examples/job_quickstart.py) — source example for the recommended quickstart edits. The matrix batch example is a planned replacement in the showcase, not yet implemented.
- [Modal getting started](https://modal.com/docs/guide/getting-started) and [parallel execution](https://modal.com/docs/guide/scale) — function authoring and invocation.
- [RunPod SDK overview](https://docs.runpod.io/sdk/overview), [quickstart](https://docs.runpod.io/sdk/quickstart), and [endpoint operations](https://docs.runpod.io/serverless/endpoints/operation-reference) — distinct authoring and existing-endpoint workflows.
