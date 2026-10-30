"""Official Nebius SDK quickstart for the SDK comparison.

Runs ``nvidia-smi`` on one requested H100 in ``eu-north1``, prints the job
ID, polls ``GetJob`` until the job reaches a terminal state, and raises
``RuntimeError`` unless the final state is ``COMPLETED``.
"""

# --- orchestration: start ---
import time
from datetime import timedelta
from uuid import uuid4

from nebius.aio.cli_config import Config
from nebius.api.nebius.ai.v1 import (
    CreateJobRequest,
    GetJobRequest,
    JobServiceClient,
    JobSpec,
)
from nebius.api.nebius.common.v1 import ResourceMetadata
from nebius.api.nebius.compute.v1 import DiskSpec as ComputeDisk
from nebius.sdk import SDK

TERMINAL_STATES = frozenset(
    {"COMPLETED", "FAILED", "CANCELLED", "ERROR"}
)
POLL_SECONDS = 1.0
# --- orchestration: end ---


def main() -> None:
    """Run nvidia-smi on one H100 and require COMPLETED."""
    # --- orchestration: start ---
    config = Config()
    project_id = config.parent_id
    if not isinstance(project_id, str) or not project_id.strip():
        raise RuntimeError("Nebius profile has no parent_id configured")
    sdk = SDK(config_reader=config, parent_id=project_id)
    try:
        client = JobServiceClient(sdk)
        request = CreateJobRequest(
            metadata=ResourceMetadata(
                parent_id=project_id,
                name=f"job-{uuid4().hex[:12]}",
            ),
            spec=JobSpec(
                image="nvidia/cuda:13.1.1-runtime-ubuntu24.04",
                container_command="nvidia-smi",
                platform="gpu-h100-sxm",
                preset="1gpu-16vcpu-200gb",
                timeout=timedelta(seconds=3600),
                shm_size_bytes=16 * 1024**3,
                disk=JobSpec.DiskSpec(
                    type=ComputeDisk.DiskType.NETWORK_SSD,
                    size_bytes=250 * 1024**3,
                ),
            ),
        )
        operation = client.create(request).wait()
        operation.sync_wait()
        job_id = operation.resource_id
        if not isinstance(job_id, str) or not job_id:
            raise RuntimeError("Create operation returned no job ID")
        print(job_id)
        while True:
            job = client.get(GetJobRequest(id=job_id)).wait()
            state = job.status.state.name
            if state in TERMINAL_STATES:
                break
            time.sleep(POLL_SECONDS)
        if state != "COMPLETED":
            raise RuntimeError(f"{job_id}: {state}")
    finally:
        sdk.sync_close()
    # --- orchestration: end ---


if __name__ == "__main__":
    main()
