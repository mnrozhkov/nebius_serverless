"""Fine-tune with Axolotl on a spot H100 and save artifacts to S3.

Uses the active Nebius profile.
"""

import nebius_serverless as ns


def main() -> None:
    """Create the Axolotl job, wait for it, and print the final record."""

    job = ns.Job(
        ["bash", "-lc", "axolotl train /workspace/data/config.yaml"],
        image="docker.io/axolotlai/axolotl:main-20260309-py3.11-cu128-2.9.1",
        gpu="h100",
        pricing="spot",
        disk="500Gi",
        timeout="24h",
        volumes=[
            "s3://axolotl-data:/workspace/data:ro",
            "s3://axolotl-artifacts:/workspace/artifacts:rw",
        ],
    )
    run = job.create()
    run.wait()
    run.display()


if __name__ == "__main__":
    main()
