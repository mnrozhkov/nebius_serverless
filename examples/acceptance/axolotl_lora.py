"""Acceptance scenario 2: the cookbook Axolotl job.

Matches the create command in
https://github.com/nebius/serverless-ai-cookbook/tree/main/templates/job-axolotl-finetune
The cookbook omits --timeout. 24h is that CLI default. Dry-run is the
default. --create submits and waits.
"""

import argparse

from _common import add_run_arguments, profile_kwargs, require_completed

import nebius_serverless as ns

IMAGE = "docker.io/axolotlai/axolotl:main-20260309-py3.11-cu128-2.9.1"
COMMAND = [
    "bash",
    "-lc",
    "curl -fsSL https://raw.githubusercontent.com/nebius/"
    "serverless-ai-cookbook/main/training/"
    "axolotl-finetuning/src/config.yaml"
    " -o /workspace/data/config.yaml"
    " && export RUN_ID=run-$(date +%Y%m%d-%H%M%S)"
    " && axolotl train /workspace/data/config.yaml"
    " && mkdir -p /workspace/data/output/$RUN_ID"
    " && cp -r /workspace/output/."
    " /workspace/data/output/$RUN_ID",
]


def main() -> None:
    args = _parser().parse_args()
    job = ns.Job(
        COMMAND,
        image=IMAGE,
        gpu="h100",
        pricing="spot",
        disk="500Gi",
        timeout="24h",
        **profile_kwargs(args),
    )
    if not args.create:
        print(job.create(dry_run=True))
        return
    run = job.create()
    print(run.id)
    require_completed(run, run.wait())


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fine-tune Qwen2.5-0.5B with the Axolotl cookbook.",
    )
    add_run_arguments(parser)
    return parser


if __name__ == "__main__":
    main()
