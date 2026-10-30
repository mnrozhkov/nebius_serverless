"""Run nvidia-smi on a remote RunPod App SDK (beta) H100 GPU."""

import subprocess

# --- orchestration: start ---
import runpod

app = runpod.App("nebius-comparison-quickstart")


@app.queue(gpu="H100", execution_timeout_ms=3600000)
# --- orchestration: end ---
def run_nvidia_smi() -> str:
    """Execute nvidia-smi in the remote worker and return stdout."""
    completed = subprocess.run(
        ["nvidia-smi"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return completed.stdout


# --- orchestration: start ---
@runpod.local_entrypoint
def main() -> None:
    """Run the remote GPU check and print verified nvidia-smi output."""
    output = run_nvidia_smi.remote()
    if not isinstance(output, str) or not output.strip():
        raise RuntimeError("nvidia-smi returned empty output")
    # --- orchestration: end ---
    print(output, end="")


if __name__ == "__main__":
    main()
