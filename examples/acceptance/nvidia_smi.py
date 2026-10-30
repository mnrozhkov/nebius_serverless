"""Acceptance scenario 1: the cookbook first job.

Matches the create command in
https://github.com/nebius/serverless-ai-cookbook/blob/main/quickstarts/first-job.md
``gpu="l40s"`` is that machine. The cookbook passes --timeout 15m. The
Jobs API minimum is 1 hour, so this script sends 1h. Dry-run is the
default. --create submits and waits.
"""

import argparse
from pathlib import Path

from _common import add_run_arguments, profile_kwargs, require_completed

import nebius_serverless as ns

YAML = Path(__file__).with_name("nvidia_smi.yaml")


def main() -> None:
    args = _parser().parse_args()
    job = ns.Job(
        ["bash", "-c", "nvidia-smi"],
        image="nvidia/cuda:13.1.1-runtime-ubuntu24.04",
        gpu="l40s",
        timeout="1h",
        name="my-job",
        **profile_kwargs(args),
    )
    if not args.create:
        from_yaml = ns.Job.from_yaml(YAML)
        print(from_yaml.create(dry_run=True))
        print(job.create(dry_run=True))
        return
    run = job.create()
    print(run.id)
    require_completed(run, run.wait(timeout=5400))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the cookbook nvidia-smi job.",
    )
    add_run_arguments(parser)
    return parser


if __name__ == "__main__":
    main()
