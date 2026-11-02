"""Fine-tune Qwen/Qwen2.5-0.5B with Axolotl on Nebius Serverless AI Jobs.

Rebuilds the Nebius Serverless AI Cookbook Axolotl recipe in Python
(training/axolotl-finetuning/README.md). Upload ``config.yaml`` to
``s3://fine-tuning-axolotl/config.yaml`` before running. Uses the active
Nebius profile.
"""

import nebius_serverless as ns


def main() -> None:
    """Create the Axolotl fine-tuning job, wait, and print the record."""
    job = ns.Job(
        [
            "bash",
            "-lc",
            "RUN_ID=run-$(date +%Y%m%d-%H%M%S)"
            " && axolotl train /workspace/data/config.yaml"
            " && mkdir -p /workspace/data/output/$RUN_ID"
            " && cp -r /workspace/output/. /workspace/data/output/$RUN_ID",
        ],
        image="docker.io/axolotlai/axolotl:main-20260309-py3.11-cu128-2.9.1",
        gpu="h100",
        pricing="spot",
        disk="500Gi",
        timeout="24h",
        volumes=["s3://fine-tuning-axolotl:/workspace/data:rw"],
    )
    run = job.create()
    run.wait()
    run.display()


if __name__ == "__main__":
    main()
