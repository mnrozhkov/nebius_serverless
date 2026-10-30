"""Focused Nebius Serverless SDK quickstart for the SDK comparison.

Runs ``nvidia-smi`` on one requested H100, prints the job ID, waits for
completion, and raises ``RuntimeError`` unless the terminal status is
``COMPLETED``.
"""

# --- orchestration: start ---
import nebius_serverless as ns

# --- orchestration: end ---


def main() -> None:
    """Run nvidia-smi on one H100 and require COMPLETED."""
    # --- orchestration: start ---
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
    # --- orchestration: end ---


if __name__ == "__main__":
    main()
