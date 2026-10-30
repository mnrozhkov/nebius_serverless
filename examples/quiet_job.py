"""Create and wait without progress on stderr.

Stdout still prints the id and the final state. ``quiet=True`` applies
only to the call that sets it. Uses the active Nebius profile.
"""

import nebius_serverless as ns

COMMAND = ["nvidia-smi"]
IMAGE = "nvidia/cuda:13.1.1-runtime-ubuntu24.04"
GPU = "h100"
TIMEOUT = "1h"


def main() -> None:
    """Create and wait with progress suppressed on both calls."""
    job = ns.Job(COMMAND, image=IMAGE, gpu=GPU, timeout=TIMEOUT)
    run = job.create(quiet=True)
    print(run.id)
    record = run.wait(quiet=True)
    print(run.id, record["status"]["state"])


if __name__ == "__main__":
    main()
