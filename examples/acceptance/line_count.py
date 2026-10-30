"""Acceptance scenario 3: three GPU jobs count lines in 30 files.

The script writes 10 files of 100 lines, 10 of 200, and 10 of 300.
`--create` uploads them to ACCEPTANCE_BUCKET and starts one job per shard.
Each job writes a report. The expected bodies are 1000, 2000, and 3000.
Dry-run is the default and does not upload.
Contract: specs/cloud-jobs.md, section 13.
"""

import argparse
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from _common import add_job_arguments, profile_kwargs, require_completed

import nebius_serverless as ns

IMAGE = "python:3.12-slim"
SHARDS = (
    ("shard-0", 100, "1000"),
    ("shard-1", 200, "2000"),
    ("shard-2", 300, "3000"),
)
COUNTER = """
import pathlib
import sys

prefix, shard = sys.argv[1], sys.argv[2]
root = pathlib.Path("/data") / prefix / "input" / shard
files = sorted(path for path in root.glob("*.txt") if path.is_file())
if len(files) != 10:
    raise SystemExit(
        f"{shard}: expected 10 files in {root}, found {len(files)}"
    )
total = 0
for path in files:
    with path.open() as handle:
        total += sum(1 for line in handle if line.strip())
out = pathlib.Path("/data") / prefix / "reports" / f"{shard}.txt"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(f"{total}\\n")
"""


def main() -> None:
    args = _parser().parse_args()
    bucket = os.environ.get("ACCEPTANCE_BUCKET")
    region = os.environ.get("NEBIUS_REGION", "eu-north1")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    prefix = f"acceptance/{stamp}"
    options = profile_kwargs(args)
    if bucket:
        options["volumes"] = [f"s3://{bucket}:/data:rw"]
    jobs = [
        ns.Job(
            ["python", "-c", COUNTER, prefix, shard],
            image=IMAGE,
            gpu=args.gpu,
            timeout="1h",
            name=f"line-count-{stamp}-{shard}",
            **dict(options),
        )
        for shard, _lines, _report in SHARDS
    ]
    if not args.create:
        for job in jobs:
            print(job.create(dry_run=True))
        return
    if not bucket:
        raise SystemExit(
            "Set ACCEPTANCE_BUCKET to the Object Storage bucket name."
        )
    endpoint = f"https://storage.{region}.nebius.cloud"
    with tempfile.TemporaryDirectory() as directory:
        root = _write_files(Path(directory))
        for shard, _lines, _report in SHARDS:
            _aws(
                "cp",
                str(root / shard),
                f"s3://{bucket}/{prefix}/input/{shard}/",
                "--recursive",
                "--endpoint-url",
                endpoint,
            )
    runs = [job.create() for job in jobs]
    for run in runs:
        print(run.id)
    reports = zip(runs, SHARDS, strict=True)
    for run, (shard, _lines, expected) in reports:
        require_completed(run, run.wait(timeout=5400))
        body = _aws(
            "cp",
            f"s3://{bucket}/{prefix}/reports/{shard}.txt",
            "-",
            "--endpoint-url",
            endpoint,
        )
        if body.strip() != expected:
            raise SystemExit(
                f"{shard} report {body.strip()!r}, expected {expected}"
            )
        print(f"{shard} {expected}")


def _write_files(root: Path) -> Path:
    for shard, lines, _report in SHARDS:
        folder = root / shard
        folder.mkdir(parents=True)
        for index in range(10):
            (folder / f"file-{index:02d}.txt").write_text("line\n" * lines)
    return root


def _aws(*arguments: str) -> str:
    completed = subprocess.run(
        ["aws", "s3", *arguments],
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise SystemExit(detail or f"aws s3 failed ({completed.returncode})")
    return completed.stdout


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Count lines in 30 files with three GPU jobs.",
    )
    add_job_arguments(parser)
    return parser


if __name__ == "__main__":
    main()
