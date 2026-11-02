"""Official Nebius SDK Axolotl fine-tuning job for the SDK comparison.

Runs ``axolotl train /workspace/data/config.yaml`` on one spot H100 in
``eu-north1`` with a 500 GiB disk, 24h timeout, and S3 volume mounts for
training data and model artifacts, then polls ``GetJob`` until
``COMPLETED``.
"""

# --- orchestration: start ---
import shlex
import time
from datetime import timedelta
from uuid import uuid4

from nebius.aio.cli_config import Config
from nebius.api.nebius.ai.v1 import (
    CreateJobRequest,
    FollowsSpotPriceSpec,
    GetJobRequest,
    JobServiceClient,
    JobSpec,
    PricingModelSpec,
)
from nebius.api.nebius.common.v1 import ResourceMetadata
from nebius.api.nebius.compute.v1 import DiskSpec as ComputeDisk
from nebius.sdk import SDK
# --- orchestration: end ---


def main() -> None:
    """Create the spot H100 Axolotl job and wait for COMPLETED."""
    # --- orchestration: start ---
    config = Config()
    project_id = config.parent_id
    sdk = SDK(config_reader=config, parent_id=project_id)
    try:
        client = JobServiceClient(sdk)
        args = " ".join(
            shlex.quote(part)
            for part in ("-lc", "axolotl train /workspace/data/config.yaml")
        )
        request = CreateJobRequest(
            metadata=ResourceMetadata(
                parent_id=project_id,
                name=f"job-{uuid4().hex[:12]}",
            ),
            spec=JobSpec(
                image=(
                    "docker.io/axolotlai/axolotl:"
                    "main-20260309-py3.11-cu128-2.9.1"
                ),
                container_command="bash",
                args=args,
                platform="gpu-h100-sxm",
                preset="1gpu-16vcpu-200gb",
                timeout=timedelta(seconds=24 * 3600),
                disk=JobSpec.DiskSpec(
                    type=ComputeDisk.DiskType.NETWORK_SSD,
                    size_bytes=500 * 1024**3,
                ),
                preemptible=True,
                pricing_model=PricingModelSpec(
                    follows_spot_price=FollowsSpotPriceSpec(),
                ),
                volumes=[
                    JobSpec.VolumeMount(
                        source="s3://axolotl-data",
                        container_path="/workspace/data",
                        mode=JobSpec.VolumeMount.Mode.READ_ONLY,
                    ),
                    JobSpec.VolumeMount(
                        source="s3://axolotl-artifacts",
                        container_path="/workspace/artifacts",
                        mode=JobSpec.VolumeMount.Mode.READ_WRITE,
                    ),
                ],
            ),
        )
        operation = client.create(request).wait()
        job_id = operation.resource_id
        while True:
            job = client.get(GetJobRequest(id=job_id)).wait()
            state = job.status.state.name
            if state in {"COMPLETED", "FAILED", "CANCELLED", "ERROR"}:
                break
            time.sleep(1.0)
        if state != "COMPLETED":
            raise RuntimeError(f"{job_id}: {state}")
    finally:
        sdk.sync_close()
    # --- orchestration: end ---


if __name__ == "__main__":
    main()
