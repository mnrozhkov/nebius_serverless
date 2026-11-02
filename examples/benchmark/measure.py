"""Reproducible line-count and SHA-256 hash measurements for SDK comparisons.

Counts nonblank, non-comment physical Python lines across all 8 comparison
variants (Quickstart and Axolotl Fine-tuning across Official Nebius SDK,
Designed Nebius SDK, Modal, and RunPod).

Counting rule (per ``specs/sdk_copmarison.md``):
1. Blank lines (``line.strip() == ""``) and comment lines
   (``line.strip().startswith("#")``, including orchestration marker lines)
   are excluded.
2. Module, class, and function docstrings in the file AST are excluded.
3. Non-excluded physical lines inside ``# --- orchestration: start ---`` ..
   ``# --- orchestration: end ---`` blocks are counted as *Orchestration*
   (or, in marker-free scripts, all non-excluded lines outside the
   ``def main() -> None:`` / ``if __name__ == "__main__": main()`` wrapper).
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
_ENTRYPOINT_WRAPPER_LINES = frozenset(
    {
        "def main() -> None:",
        'if __name__ == "__main__":',
        "main()",
    }
)


@dataclass(frozen=True)
class FileCount:
    """Line counts and SHA-256 digest for one source file."""

    relpath: str
    sha256: str
    python_total: int
    orchestration: int
    workload_and_data: int


@dataclass(frozen=True)
class VariantMeasurement:
    """Aggregated measurements for one task and provider variant."""

    task: str
    variant: str
    files: tuple[FileCount, ...]
    python_total: int
    orchestration: int
    workload_and_data: int
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
    """Return 1-based physical line numbers of docstrings in ``source``."""
    tree = ast.parse(source)
    return _docstring_lines_in_tree(tree)


def count_python_file(path: Path) -> FileCount:
    """Count total, orchestration, and workload lines in ``path``."""
    source = path.read_text(encoding="utf-8")
    doc_lines = docstring_line_numbers(source)
    has_markers = ORCHESTRATION_START in source
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
        if in_orchestration or (
            not has_markers and stripped not in _ENTRYPOINT_WRAPPER_LINES
        ):
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
    other_setup: str,
    concepts_exposed: tuple[str, ...],
    interfaces_crossed: tuple[str, ...],
    verified_outcome: str = "Pending live run",
) -> VariantMeasurement:
    files = tuple(
        count_python_file(ROOT / relpath) for relpath in py_relpaths
    )
    python_total = sum(item.python_total for item in files)
    orchestration = sum(item.orchestration for item in files)
    workload_and_data = sum(item.workload_and_data for item in files)
    return VariantMeasurement(
        task=task,
        variant=variant,
        files=files,
        python_total=python_total,
        orchestration=orchestration,
        workload_and_data=workload_and_data,
        other_setup=other_setup,
        concepts_exposed=concepts_exposed,
        interfaces_crossed=interfaces_crossed,
        verified_outcome=verified_outcome,
    )


def measure_all() -> tuple[
    tuple[VariantMeasurement, ...], tuple[ReductionSummary, ...]
]:
    """Compute measurements for all 8 variants and Nebius reductions."""
    variants = (
        _measure_variant(
            task="Quickstart",
            variant="Official Nebius SDK",
            py_relpaths=("examples/benchmark/nebius/quickstart.py",),
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
            verified_outcome=(
                "Verified live on eu-north1 H100 "
                "(aijob-e00v6x2f50trfqv8dn -> COMPLETED; "
                "NVIDIA H100 80GB HBM3)"
            ),
        ),
        _measure_variant(
            task="Quickstart",
            variant="Designed Nebius SDK",
            py_relpaths=("examples/job_quickstart.py",),
            other_setup=(
                "4 steps: uv sync; Nebius CLI profile + parent_id; "
                "eu-north1 H100 quota & default subnet; "
                "optional nebius ai job logs <id>"
            ),
            concepts_exposed=(
                "ns.Job",
                "job.create",
                "run.wait",
                "run.display",
            ),
            interfaces_crossed=("Python", "Nebius CLI profile & logs"),
            verified_outcome=(
                "Verified live on eu-north1 H100 "
                "(aijob-e00rzxph84v14b5ddz -> COMPLETED; "
                "NVIDIA H100 80GB HBM3)"
            ),
        ),
        _measure_variant(
            task="Quickstart",
            variant="Modal",
            py_relpaths=("examples/benchmark/modal/quickstart.py",),
            other_setup=(
                "3 steps: uv sync --project examples/benchmark/modal; "
                "modal setup; modal run"
            ),
            concepts_exposed=(
                "modal.App",
                "@app.function",
                "@app.local_entrypoint",
                ".remote()",
            ),
            interfaces_crossed=("Python", "Modal CLI"),
            verified_outcome=(
                "Pending live run (Modal token missing: run modal token new)"
            ),
        ),
        _measure_variant(
            task="Quickstart",
            variant="RunPod",
            py_relpaths=("examples/benchmark/runpod/quickstart.py",),
            other_setup=(
                "3 steps: uv sync --project examples/benchmark/runpod; "
                "rp login; rp flash dev --once"
            ),
            concepts_exposed=(
                "runpod.App",
                "@app.queue",
                "@runpod.local_entrypoint",
                ".remote()",
            ),
            interfaces_crossed=("Python", "RunPod Flash CLI"),
            verified_outcome=(
                "Pending live run (RunPod API key missing: run rp login)"
            ),
        ),
        _measure_variant(
            task="Fine-tuning (Axolotl)",
            variant="Official Nebius SDK",
            py_relpaths=("examples/benchmark/nebius/axolotl_lora.py",),
            other_setup=(
                "5 steps: uv sync; Nebius CLI profile + parent_id; "
                "eu-north1 spot H100 quota & subnet; "
                "S3 buckets axolotl-data & axolotl-artifacts; "
                "upload config.yaml & dataset"
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
                "PricingModelSpec",
                "FollowsSpotPriceSpec",
                "JobSpec.VolumeMount",
                "JobSpec.VolumeMount.Mode",
                "operation.wait",
                "operation.sync_wait",
                "GetJobRequest",
                "TERMINAL_STATES polling loop",
                "sdk.sync_close",
            ),
            interfaces_crossed=(
                "Python",
                "Nebius CLI profile & logs",
                "Object Storage mounts",
            ),
            verified_outcome=(
                "Verified dry-run & offline request mapping "
                "(live spot H100 run pending bucket upload)"
            ),
        ),
        _measure_variant(
            task="Fine-tuning (Axolotl)",
            variant="Designed Nebius SDK",
            py_relpaths=("examples/train/axolotl_lora.py",),
            other_setup=(
                "5 steps: uv sync; Nebius CLI profile + parent_id; "
                "eu-north1 spot H100 quota & subnet; "
                "S3 buckets axolotl-data & axolotl-artifacts; "
                "upload config.yaml & dataset"
            ),
            concepts_exposed=(
                "ns.Job",
                "pricing='spot'",
                "disk='500Gi'",
                "volumes mount strings",
                "job.create",
                "run.wait",
                "run.display",
            ),
            interfaces_crossed=(
                "Python",
                "Nebius CLI profile & logs",
                "Object Storage mounts",
            ),
            verified_outcome=(
                "Verified dry-run & offline request mapping "
                "(live spot H100 run pending bucket upload)"
            ),
        ),
        _measure_variant(
            task="Fine-tuning (Axolotl)",
            variant="Modal",
            py_relpaths=("examples/benchmark/modal/axolotl_lora.py",),
            other_setup=(
                "4 steps: uv sync --project examples/benchmark/modal; "
                "modal setup; modal volume put axolotl-data config.yaml; "
                "modal run"
            ),
            concepts_exposed=(
                "modal.App",
                "modal.Image.from_registry",
                "modal.Volume.from_name",
                "@app.function",
                "artifacts.commit()",
                "@app.local_entrypoint",
                ".remote()",
            ),
            interfaces_crossed=(
                "Python",
                "Modal CLI",
                "Modal Volumes",
            ),
            verified_outcome=(
                "Pending live run (Modal token missing: run modal token new)"
            ),
        ),
        _measure_variant(
            task="Fine-tuning (Axolotl)",
            variant="RunPod",
            py_relpaths=("examples/benchmark/runpod/axolotl_lora.py",),
            other_setup=(
                "4 steps: uv sync --project examples/benchmark/runpod; "
                "rp login; upload config.yaml to axolotl-workspace volume; "
                "rp flash dev --once"
            ),
            concepts_exposed=(
                "runpod.App",
                "runpod.NetworkVolume",
                "@app.task",
                "timeout CLI wrapper",
                "@runpod.local_entrypoint",
                ".remote()",
            ),
            interfaces_crossed=(
                "Python",
                "RunPod Flash CLI",
                "RunPod NetworkVolume",
            ),
            verified_outcome=(
                "Pending live run (RunPod API key missing: run rp login)"
            ),
        ),
    )

    by_key = {(item.task, item.variant): item for item in variants}
    reductions: list[ReductionSummary] = []
    for task in ("Quickstart", "Fine-tuning (Axolotl)"):
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
