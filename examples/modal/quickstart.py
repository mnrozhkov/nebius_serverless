"""Run nvidia-smi on a remote Modal H100 GPU and verify the output."""

import subprocess

# --- orchestration: start ---
import modal

app = modal.App("nebius-comparison-quickstart")


@app.function(gpu="H100!", timeout=3600)
# --- orchestration: end ---
def run_nvidia_smi() -> str:
    """Execute nvidia-smi in the remote container and return stdout."""
    completed = subprocess.run(
        ["nvidia-smi"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return completed.stdout


# --- orchestration: start ---
@app.local_entrypoint()
def main() -> None:
    """Run the remote GPU check and print verified nvidia-smi output."""
    output = run_nvidia_smi.remote()
    if not output.strip():
        raise RuntimeError("nvidia-smi returned empty output")
    # --- orchestration: end ---
    print(output, end="")
