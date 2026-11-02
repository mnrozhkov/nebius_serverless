# Parallel Axolotl Fine-Tuning

`axolotl_sweep.py` launches two Nebius Serverless AI Jobs in parallel. Upload both Axolotl configs to Object Storage first, then each job mounts the same bucket, trains on a spot H100, and copies checkpoints into a separate folder under that volume.

## Files

- `configs/qwen_0_5b.yaml` — QLoRA for `Qwen/Qwen2.5-0.5B` (`learning_rate: 2e-4`, `lora_r: 8`)
- `configs/qwen_1_5b.yaml` — QLoRA for `Qwen/Qwen2.5-1.5B` (`learning_rate: 1e-4`, `lora_r: 16`)
- `axolotl_sweep.py` — Creates both jobs, waits for each, calls `run.display()`

## Config delivery and outputs

Both YAML files keep `output_dir: /workspace/output` on container-local disk because Axolotl's `debug.log` appends are not supported on an S3 FUSE mount. After training, each container copies `/workspace/output/.` into:

- `s3://fine-tuning-axolotl/output/qwen_0_5b/`
- `s3://fine-tuning-axolotl/output/qwen_1_5b/`

## Usage

1. Upload both Axolotl configs to your Object Storage bucket:

```bash
aws s3 cp examples/parallel_jobs/configs/ s3://fine-tuning-axolotl/configs/ \
  --recursive \
  --endpoint-url https://storage.eu-north1.nebius.cloud
```

2. Run the parallel sweep:

```bash
uv run python examples/parallel_jobs/axolotl_sweep.py
```

The bucket must exist and be mountable as `s3://fine-tuning-axolotl:/workspace/data:rw`. Quota should cover two concurrent H100 jobs.
