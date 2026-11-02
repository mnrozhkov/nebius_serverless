"""Run two Axolotl fine-tunes in parallel and save adapters to one volume.

Upload ``configs/qwen_0_5b.yaml`` and ``configs/qwen_1_5b.yaml`` to
``s3://fine-tuning-axolotl/configs/`` before running. Both jobs mount that
bucket and copy checkpoints into separate folders under
``/workspace/data/output/``. Uses the active Nebius profile.
"""

import nebius_serverless as ns


def main() -> None:
    """Create both jobs, wait for each, and display the final records."""
    jobs = (
        ns.Job(
            [
                "bash",
                "-lc",
                "axolotl train /workspace/data/configs/qwen_0_5b.yaml"
                " && mkdir -p /workspace/data/output/qwen_0_5b"
                " && cp -r /workspace/output/."
                " /workspace/data/output/qwen_0_5b",
            ],
            image=(
                "docker.io/axolotlai/axolotl:"
                "main-20260309-py3.11-cu128-2.9.1"
            ),
            gpu="h100",
            pricing="spot",
            disk="500Gi",
            timeout="24h",
            volumes=["s3://fine-tuning-axolotl:/workspace/data:rw"],
            name="axolotl-qwen-0.5b",
        ),
        ns.Job(
            [
                "bash",
                "-lc",
                "axolotl train /workspace/data/configs/qwen_1_5b.yaml"
                " && mkdir -p /workspace/data/output/qwen_1_5b"
                " && cp -r /workspace/output/."
                " /workspace/data/output/qwen_1_5b",
            ],
            image=(
                "docker.io/axolotlai/axolotl:"
                "main-20260309-py3.11-cu128-2.9.1"
            ),
            gpu="h100",
            pricing="spot",
            disk="500Gi",
            timeout="24h",
            volumes=["s3://fine-tuning-axolotl:/workspace/data:rw"],
            name="axolotl-qwen-1.5b",
        ),
    )

    runs = [job.create() for job in jobs]
    for run in runs:
        run.wait()
        run.display()


if __name__ == "__main__":
    main()
