"""The README quickstart.

``["nvidia-smi"]``, ``gpu="h100"``, and timeout ``1h``. Uses the active
Nebius profile.
"""

import nebius_serverless as ns

COMMAND = ["nvidia-smi"]
IMAGE = "nvidia/cuda:13.1.1-runtime-ubuntu24.04"
GPU = "h100"
TIMEOUT = "1h"


def main() -> None:
    """Create the README job and follow it.

    Progress is on stderr. The script does not print the job JSON.
    """
    job = ns.Job(COMMAND, image=IMAGE, gpu=GPU, timeout=TIMEOUT)
    run = job.create()
    saved_id = run.id
    run.get()
    run.wait()
    if run.status != "COMPLETED":
        raise SystemExit(f"{run.id} ended {run.status}")
    run.cancel()
    ns.jobs.get(saved_id)


if __name__ == "__main__":
    main()
