"""Fine-tune with the cookbook Axolotl job.

Matches the create command in
https://github.com/nebius/serverless-ai-cookbook/tree/main/templates/job-axolotl-finetune
The cookbook omits --timeout. 24h is that CLI default. Uses the active
Nebius profile.
"""

import nebius_serverless as ns

IMAGE = "docker.io/axolotlai/axolotl:main-20260309-py3.11-cu128-2.9.1"
GPU = "h100"
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
    """Create the Axolotl job and wait for it."""
    job = ns.Job(
        COMMAND,
        image=IMAGE,
        gpu=GPU,
        pricing="spot",
        disk="500Gi",
        timeout="24h",
    )
    run = job.create()
    print(run.id)
    run.wait()
    if run.status != "COMPLETED":
        raise SystemExit(f"{run.id} ended {run.status}")


if __name__ == "__main__":
    main()
