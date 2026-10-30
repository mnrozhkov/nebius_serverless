"""Reproducible line-count and SHA-256 hash measurements for SDK comparisons.

Counts nonblank, non-comment physical Python lines across all 10 comparison
variants (Quickstart and Batch across Official Nebius SDK, Designed Nebius SDK,
Modal, RunPod App SDK beta, and RunPod Endpoint SDK client + worker).

Counting rule (per ``specs/sdk_copmarison.md``):
1. Blank lines (``line.strip() == ""``) and comment lines
   (``line.strip().startswith("#")``, including orchestration marker lines)
   are excluded.
2. Module, class, and function docstrings in the file AST are excluded. When a
   module defines an embedded ``WORKER`` string literal containing Python code,
   docstrings inside ``WORKER`` are also excluded while ``WORKER = \"\"\"`` and
   closing ``\"\"\"`` delimiter lines are counted.
3. Non-excluded physical lines inside ``# --- orchestration: start ---`` ..
   ``# --- orchestration: end ---`` blocks are counted as *Orchestration*.
4. All remaining non-excluded physical lines are counted as *Workload and data*
   (``workload_and_data = python_total - orchestration``).
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATION_START = "# --- orchestration: start ---"
ORCHESTRATION_END = "# --- orchestration: end ---"


@dataclass(frozen=True)
class FileCount:
    """Line counts and SHA-256 digest for one source file."""

    relpath: str
    sha256: str
    python_total: int
    orchestration: int
    workload_and_data: int


@dataclass(frozen=True)
class NonPythonFileCount:
    """Line count and SHA-256 digest for a non-Python setup file."""

    relpath: str
    sha256: str
    nonblank_lines: int


@dataclass(frozen=True)
class VariantMeasurement:
    """Aggregated measurements for one task and provider variant."""

    task: str
    variant: str
    files: tuple[FileCount, ...]
    non_python_files: tuple[NonPythonFileCount, ...]
    python_total: int
    orchestration: int
    workload_and_data: int
    non_python_lines: int
    other_setup: str
    concepts_exposed: tuple[str, ...]
    interfaces_crossed: tuple[str, ...]
    verified_outcome: str = "Pending live run"
    onboarding_time: str = "Pending study"


@dataclass(frozen=True)
class ReductionSummary:
    """Percentage reduction from Official Nebius SDK to Designed Nebius SDK."""

    task: str
    before_orchestration: int
    after_orchestration: int
    orchestration_reduction_pct: float
    before_total: int
    after_total: int
    total_reduction_pct: float


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 digest of ``path``."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _docstring_lines_in_tree(
    tree: ast.AST, line_offset: int = 0
) -> set[int]:
    """Return 1-based line numbers occupied by docstrings in ``tree``."""
    lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(
            node,
            (
                ast.Module,
                ast.FunctionDef,
                ast.AsyncFunctionDef,
                ast.ClassDef,
            ),
        ):
            continue
        if not node.body:
            continue
        first = node.body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
            and first.lineno is not None
            and first.end_lineno is not None
        ):
            for lineno in range(first.lineno, first.end_lineno + 1):
                lines.add(lineno + line_offset)
    return lines


def docstring_line_numbers(source: str) -> set[int]:
    """Return 1-based physical line numbers of docstrings in ``source``.

    Includes docstrings inside a top-level ``WORKER`` string assignment when
    present so embedded and non-embedded worker functions are counted under the
    same rule.
    """
    tree = ast.parse(source)
    excluded = _docstring_lines_in_tree(tree)
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "WORKER"
            for target in node.targets
        ):
            continue
        if (
            isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
            and node.value.lineno is not None
        ):
            worker_source = node.value.value
            worker_tree = ast.parse(worker_source)
            excluded |= _docstring_lines_in_tree(
                worker_tree, line_offset=node.value.lineno - 1
            )
    return excluded


def count_python_file(path: Path) -> FileCount:
    """Count total, orchestration, and workload lines in ``path``."""
    source = path.read_text(encoding="utf-8")
    doc_lines = docstring_line_numbers(source)
    in_orchestration = False
    python_total = 0
    orchestration = 0

    for lineno, raw_line in enumerate(source.splitlines(), start=1):
        stripped = raw_line.strip()
        if stripped == ORCHESTRATION_START:
            if in_orchestration:
                raise ValueError(
                    f"{path}:{lineno}: nested {ORCHESTRATION_START!r}"
                )
            in_orchestration = True
            continue
        if stripped == ORCHESTRATION_END:
            if not in_orchestration:
                raise ValueError(
                    f"{path}:{lineno}: unmatched {ORCHESTRATION_END!r}"
                )
            in_orchestration = False
            continue
        if not stripped or stripped.startswith("#"):
            continue
        if lineno in doc_lines:
            continue
        python_total += 1
        if in_orchestration:
            orchestration += 1

    if in_orchestration:
        raise ValueError(f"{path}: unclosed {ORCHESTRATION_START!r}")

    relpath = path.resolve().relative_to(ROOT).as_posix()
    return FileCount(
        relpath=relpath,
        sha256=sha256_file(path),
        python_total=python_total,
        orchestration=orchestration,
        workload_and_data=python_total - orchestration,
    )


def count_non_python_file(path: Path) -> NonPythonFileCount:
    """Count nonblank, non-comment physical lines in a setup file."""
    source = path.read_text(encoding="utf-8")
    nonblank = 0
    for raw_line in source.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        nonblank += 1
    relpath = path.resolve().relative_to(ROOT).as_posix()
    return NonPythonFileCount(
        relpath=relpath,
        sha256=sha256_file(path),
        nonblank_lines=nonblank,
    )


def pct_reduction(before: int, after: int) -> float:
    """Return ``(before - after) / before * 100`` rounded to 1 decimal."""
    if before <= 0:
        raise ValueError(f"before must be positive, got {before}")
    return round((before - after) / before * 100.0, 1)


def _measure_variant(
    *,
    task: str,
    variant: str,
    py_relpaths: tuple[str, ...],
    non_py_relpaths: tuple[str, ...] = (),
    other_setup: str,
    concepts_exposed: tuple[str, ...],
    interfaces_crossed: tuple[str, ...],
) -> VariantMeasurement:
    files = tuple(
        count_python_file(ROOT / relpath) for relpath in py_relpaths
    )
    non_py_files = tuple(
        count_non_python_file(ROOT / relpath) for relpath in non_py_relpaths
    )
    python_total = sum(item.python_total for item in files)
    orchestration = sum(item.orchestration for item in files)
    workload_and_data = sum(item.workload_and_data for item in files)
    non_python_lines = sum(item.nonblank_lines for item in non_py_files)
    return VariantMeasurement(
        task=task,
        variant=variant,
        files=files,
        non_python_files=non_py_files,
        python_total=python_total,
        orchestration=orchestration,
        workload_and_data=workload_and_data,
        non_python_lines=non_python_lines,
        other_setup=other_setup,
        concepts_exposed=concepts_exposed,
        interfaces_crossed=interfaces_crossed,
    )


def measure_all() -> tuple[
    tuple[VariantMeasurement, ...], tuple[ReductionSummary, ...]
]:
    """Compute measurements for all 10 variants and Nebius reductions."""
    variants = (
        _measure_variant(
            task="Quickstart",
            variant="Official Nebius SDK",
            py_relpaths=("examples/official/quickstart.py",),
            other_setup=(
                "4 steps: uv sync; Nebius CLI profile + parent_id; "
                "eu-north1 H100 quota & default subnet; "
                "optional nebius ai job logs <id>"
            ),
            concepts_exposed=(
                "Config",
                "SDK",
                "JobServiceClient",
                "CreateJobRequest",
                "ResourceMetadata",
                "JobSpec",
                "JobSpec.DiskSpec",
                "ComputeDisk.DiskType",
                "operation.wait",
                "operation.sync_wait",
                "GetJobRequest",
                "TERMINAL_STATES polling loop",
                "sdk.sync_close",
            ),
            interfaces_crossed=("Python", "Nebius CLI profile & logs"),
        ),
        _measure_variant(
            task="Quickstart",
            variant="Designed Nebius SDK",
            py_relpaths=("examples/comparison/quickstart.py",),
            other_setup=(
                "4 steps: uv sync; Nebius CLI profile + parent_id; "
                "eu-north1 H100 quota & default subnet; "
                "optional nebius ai job logs <id>"
            ),
            concepts_exposed=(
                "ns.Job",
                "job.create",
                "run.id",
                "run.wait",
                "run.status",
            ),
            interfaces_crossed=("Python", "Nebius CLI profile & logs"),
        ),
        _measure_variant(
            task="Quickstart",
            variant="Modal",
            py_relpaths=("examples/modal/quickstart.py",),
            other_setup=(
                "3 steps: uv sync --project examples/modal; "
                "modal setup; modal run"
            ),
            concepts_exposed=(
                "modal.App",
                "@app.function",
                "@app.local_entrypoint",
                ".remote()",
            ),
            interfaces_crossed=("Python", "Modal CLI"),
        ),
        _measure_variant(
            task="Quickstart",
            variant="RunPod App SDK (beta)",
            py_relpaths=("examples/runpod/app/quickstart.py",),
            other_setup=(
                "3 steps: uv sync --project examples/runpod; "
                "rp login; rp flash dev --once"
            ),
            concepts_exposed=(
                "runpod.App",
                "@app.queue",
                "@runpod.local_entrypoint",
                ".remote()",
            ),
            interfaces_crossed=("Python", "RunPod Flash CLI"),
        ),
        _measure_variant(
            task="Quickstart",
            variant="RunPod Endpoint SDK",
            py_relpaths=(
                "examples/runpod/endpoint/quickstart_client.py",
                "examples/runpod/endpoint/quickstart_worker.py",
            ),
            non_py_relpaths=(
                "examples/runpod/endpoint/Dockerfile",
                "examples/runpod/endpoint/requirements.txt",
            ),
            other_setup=(
                "9 non-Python lines (Dockerfile + requirements.txt) + "
                "5 steps: uv sync; docker build & push; create H100 endpoint; "
                "export RUNPOD_API_KEY & RUNPOD_ENDPOINT_ID; run client"
            ),
            concepts_exposed=(
                "handler(job)",
                "runpod.serverless.start",
                "runpod.api_key",
                "runpod.Endpoint",
                "endpoint.run",
                "job.job_id",
                "job.output",
                "job.status",
            ),
            interfaces_crossed=(
                "Python",
                "Docker CLI",
                "Container registry",
                "RunPod console/API",
            ),
        ),
        _measure_variant(
            task="Batch (3 sizes)",
            variant="Official Nebius SDK",
            py_relpaths=("examples/official/matrix_multiply.py",),
            other_setup=(
                "6 steps: uv sync; Nebius CLI profile + parent_id; "
                "eu-north1 H100 quota & subnet; Object Storage bucket; "
                "AWS CLI v2 credentials; manual job & S3 cleanup"
            ),
            concepts_exposed=(
                "Config",
                "SDK",
                "JobServiceClient",
                "shlex.quote",
                "CreateJobRequest",
                "ResourceMetadata",
                "JobSpec",
                "JobSpec.DiskSpec",
                "ComputeDisk.DiskType",
                "JobSpec.VolumeMount",
                "operation.wait",
                "operation.sync_wait",
                "GetJobRequest",
                "TERMINAL_STATES polling loop",
                "sdk.sync_close",
            ),
            interfaces_crossed=(
                "Python",
                "Nebius CLI profile & cleanup",
                "Object Storage mount",
                "AWS CLI v2",
            ),
        ),
        _measure_variant(
            task="Batch (3 sizes)",
            variant="Designed Nebius SDK",
            py_relpaths=("examples/batch/matrix_multiply.py",),
            other_setup=(
                "6 steps: uv sync; Nebius CLI profile + parent_id; "
                "eu-north1 H100 quota & subnet; Object Storage bucket; "
                "AWS CLI v2 credentials; manual job & S3 cleanup"
            ),
            concepts_exposed=(
                "ns.Job",
                "volumes mount string",
                "job.create",
                "run.id",
                "run.wait",
                "run.status",
            ),
            interfaces_crossed=(
                "Python",
                "Nebius CLI profile & cleanup",
                "Object Storage mount",
                "AWS CLI v2",
            ),
        ),
        _measure_variant(
            task="Batch (3 sizes)",
            variant="Modal",
            py_relpaths=("examples/modal/matrix_multiply.py",),
            other_setup=(
                "3 steps + remote image build: uv sync --project "
                "examples/modal; modal setup; modal run "
                "(builds debian_slim + torch==2.6.0)"
            ),
            concepts_exposed=(
                "modal.Image.debian_slim.pip_install",
                "modal.App",
                "@app.function",
                "@app.local_entrypoint",
                ".map()",
            ),
            interfaces_crossed=(
                "Python",
                "Modal CLI",
                "Modal remote image builder",
            ),
        ),
        _measure_variant(
            task="Batch (3 sizes)",
            variant="RunPod App SDK (beta)",
            py_relpaths=("examples/runpod/app/matrix_multiply.py",),
            other_setup=(
                "3 steps + remote dependency install: uv sync --project "
                "examples/runpod; rp login; rp flash dev --once "
                "(installs dependencies=['torch==2.6.0'])"
            ),
            concepts_exposed=(
                "runpod.App",
                "@app.queue(dependencies=...)",
                "@runpod.local_entrypoint",
                ".spawn()",
                "job.id",
                "job.result()",
            ),
            interfaces_crossed=(
                "Python",
                "RunPod Flash CLI",
                "RunPod worker dependency installer",
            ),
        ),
        _measure_variant(
            task="Batch (3 sizes)",
            variant="RunPod Endpoint SDK",
            py_relpaths=(
                "examples/runpod/endpoint/matrix_client.py",
                "examples/runpod/endpoint/matrix_worker.py",
            ),
            non_py_relpaths=(
                "examples/runpod/endpoint/Dockerfile",
                "examples/runpod/endpoint/requirements.txt",
            ),
            other_setup=(
                "9 non-Python lines (Dockerfile + requirements.txt) + "
                "5 steps: uv sync; docker build & push; create H100 endpoint; "
                "export RUNPOD_API_KEY & RUNPOD_ENDPOINT_ID; run client"
            ),
            concepts_exposed=(
                "handler(job)",
                "runpod.serverless.start",
                "runpod.api_key",
                "runpod.Endpoint",
                "endpoint.run",
                "job.job_id",
                "job.output",
                "job.status",
            ),
            interfaces_crossed=(
                "Python",
                "Docker CLI",
                "Container registry",
                "RunPod console/API",
            ),
        ),
    )

    by_key = {(item.task, item.variant): item for item in variants}
    reductions: list[ReductionSummary] = []
    for task in ("Quickstart", "Batch (3 sizes)"):
        before = by_key[(task, "Official Nebius SDK")]
        after = by_key[(task, "Designed Nebius SDK")]
        reductions.append(
            ReductionSummary(
                task=task,
                before_orchestration=before.orchestration,
                after_orchestration=after.orchestration,
                orchestration_reduction_pct=pct_reduction(
                    before.orchestration, after.orchestration
                ),
                before_total=before.python_total,
                after_total=after.python_total,
                total_reduction_pct=pct_reduction(
                    before.python_total, after.python_total
                ),
            )
        )
    return variants, tuple(reductions)


def format_markdown_report() -> str:
    """Render variant counts, reductions, and SHA256s as Markdown."""
    variants, reductions = measure_all()
    lines: list[str] = [
        "# SDK Comparison Measurements",
        "",
        "## Summary Table",
        "",
        (
            "| Task and variant | Python total | Orchestration | "
            "Workload and data | Other setup | Verified outcome |"
        ),
        "| --- | ---: | ---: | ---: | --- | --- |",
    ]
    for item in variants:
        label = f"{item.task} — {item.variant}"
        lines.append(
            f"| {label} | {item.python_total} | {item.orchestration} | "
            f"{item.workload_and_data} | {item.other_setup} | "
            f"{item.verified_outcome} |"
        )

    lines.extend(
        [
            "",
            "## Nebius Before/After Reductions",
            "",
            (
                "| Task | Orchestration (before → after) | "
                "Orchestration reduction | Whole-example Python "
                "(before → after) | Whole-example reduction |"
            ),
            "| --- | --- | ---: | --- | ---: |",
        ]
    )
    for red in reductions:
        lines.append(
            f"| {red.task} | "
            f"{red.before_orchestration} → {red.after_orchestration} | "
            f"{red.orchestration_reduction_pct:.1f}% | "
            f"{red.before_total} → {red.after_total} | "
            f"{red.total_reduction_pct:.1f}% |"
        )

    lines.extend(
        [
            "",
            "## File Breakdown and SHA-256 Snapshots",
            "",
            (
                "| File | Python total | Orchestration | "
                "Workload and data | SHA-256 |"
            ),
            "| --- | ---: | ---: | ---: | --- |",
        ]
    )
    seen_files: set[str] = set()
    for item in variants:
        for fc in item.files:
            if fc.relpath in seen_files:
                continue
            seen_files.add(fc.relpath)
            lines.append(
                f"| `{fc.relpath}` | {fc.python_total} | "
                f"{fc.orchestration} | {fc.workload_and_data} | "
                f"`{fc.sha256}` |"
            )
    for item in variants:
        for npc in item.non_python_files:
            if npc.relpath in seen_files:
                continue
            seen_files.add(npc.relpath)
            lines.append(
                f"| `{npc.relpath}` (non-Python) | "
                f"{npc.nonblank_lines} | — | — | `{npc.sha256}` |"
            )

    return "\n".join(lines) + "\n"


def main() -> None:
    """Print the comparison measurements as Markdown or JSON."""
    parser = argparse.ArgumentParser(
        description="Measure SDK comparison line counts and SHA-256 hashes."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit measurements as formatted JSON instead of Markdown.",
    )
    args = parser.parse_args()
    if args.json:
        variants, reductions = measure_all()
        payload = {
            "variants": [asdict(item) for item in variants],
            "reductions": [asdict(item) for item in reductions],
        }
        print(json.dumps(payload, indent=2))
        return
    print(format_markdown_report(), end="")


if __name__ == "__main__":
    main()
