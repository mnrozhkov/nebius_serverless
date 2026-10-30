"""RunPod Serverless Endpoint worker handler for the nvidia-smi quickstart."""

import subprocess

# --- orchestration: start ---
import runpod

# --- orchestration: end ---


def run_nvidia_smi() -> str:
    """Execute nvidia-smi in the worker container and return stdout."""
    completed = subprocess.run(
        ["nvidia-smi"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return completed.stdout


# --- orchestration: start ---
def handler(job: dict[str, object]) -> dict[str, str]:
    """Handle one RunPod serverless job request by running nvidia-smi."""
    del job
    return {"stdout": run_nvidia_smi()}


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
# --- orchestration: end ---
