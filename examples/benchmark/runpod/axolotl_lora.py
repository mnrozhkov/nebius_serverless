"""Fine-tune with Axolotl on a RunPod H100 GPU with a network volume."""

# --- orchestration: start ---
import runpod

app = runpod.App("axolotl-training")
workspace = runpod.NetworkVolume("axolotl-workspace", size=500)


@app.task(
    image="docker.io/axolotlai/axolotl:main-20260309-py3.11-cu128-2.9.1",
    gpu="H100",
    min_cuda_version="12.8",
    container_disk_gb=500,
    mounts={"/workspace": workspace},
)
# --- orchestration: end ---
def train() -> dict[str, str]:
    """Run Axolotl training with a 24h timeout and return the output path."""
    import subprocess

    subprocess.run(
        [
            "timeout", "--kill-after=60s", "24h",
            "axolotl", "train", "/workspace/data/config.yaml",
        ],
        check=True,
    )
    return {"output_dir": "/workspace/artifacts"}


# --- orchestration: start ---
@runpod.local_entrypoint
def main() -> None:
    """Run the remote Axolotl training task and print the output."""
    print(train.remote())
# --- orchestration: end ---
