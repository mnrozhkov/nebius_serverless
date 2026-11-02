"""Fine-tune with Axolotl on a Modal H100 GPU and persist artifacts."""

import subprocess

# --- orchestration: start ---
import modal

app = modal.App("axolotl-training")

image = modal.Image.from_registry(
    "docker.io/axolotlai/axolotl:main-20260309-py3.11-cu128-2.9.1"
)
data = modal.Volume.from_name("axolotl-data", create_if_missing=True)
artifacts = modal.Volume.from_name("axolotl-artifacts", create_if_missing=True)


@app.function(
    image=image,
    gpu="H100",
    ephemeral_disk=500 * 1024,  # MiB: 500 GiB
    timeout=24 * 60 * 60,
    volumes={
        "/workspace/data": data,
        "/workspace/artifacts": artifacts,
    },
)
# --- orchestration: end ---
def train() -> None:
    """Run Axolotl training in the container and commit artifacts."""
    subprocess.run(
        ["bash", "-lc", "axolotl train /workspace/data/config.yaml"],
        check=True,
    )
    # --- orchestration: start ---
    artifacts.commit()


@app.local_entrypoint()
def main() -> None:
    """Run the remote Axolotl training function."""
    train.remote()
# --- orchestration: end ---
