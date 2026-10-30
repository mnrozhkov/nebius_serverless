"""Caller client for the RunPod Serverless Endpoint nvidia-smi quickstart."""

import os

# --- orchestration: start ---
import runpod

# --- orchestration: end ---


def main() -> None:
    """Submit a request to a deployed RunPod endpoint and verify output."""
    # --- orchestration: start ---
    runpod.api_key = os.environ["RUNPOD_API_KEY"]
    endpoint = runpod.Endpoint(os.environ["RUNPOD_ENDPOINT_ID"])
    job = endpoint.run({"command": "nvidia-smi"})
    print(job.job_id)
    output = job.output(timeout=3600)
    status = job.status()
    if status != "COMPLETED":
        raise RuntimeError(f"{job.job_id}: {status}")
    # --- orchestration: end ---
    if not isinstance(output, dict):
        raise RuntimeError(f"Expected dict output, got {type(output)!r}")
    stdout = output.get("stdout")
    if not isinstance(stdout, str) or not stdout.strip():
        raise RuntimeError("nvidia-smi returned empty output")
    print(stdout, end="")


if __name__ == "__main__":
    main()
