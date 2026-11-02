# Parallel Axolotl Fine-Tuning

`axolotl_sweep.py` launches two Nebius Serverless AI Jobs in parallel. Each job injects a local Axolotl config into the container (`--inject-file` / `inject_files=`), trains on a spot H100, and copies checkpoints into a separate folder on the same Object Storage volume.

## Files

- `configs/qwen_0_5b.yaml` — QLoRA for `Qwen/Qwen2.5-0.5B` (`learning_rate: 2e-4`, `lora_r: 8`)
- `configs/qwen_1_5b.yaml` — QLoRA for `Qwen/Qwen2.5-1.5B` (`learning_rate: 1e-4`, `lora_r: 16`)
- `axolotl_sweep.py` — Creates both jobs, waits for each, calls `run.display()`

## Config delivery and outputs

Configs stay on your machine. `inject_files=["local.yaml:/workspace/config.yaml"]` sends each file with the create request (same as Nebius CLI [`--inject-file`](https://docs.nebius.com/cli/reference/ai/create); max 64 KiB). You do not upload the YAMLs to Object Storage first.

Both YAML files keep `output_dir: /workspace/output` on container-local disk because Axolotl's `debug.log` appends are not supported on an S3 FUSE mount. After training, each container copies `/workspace/output/.` into:

- `s3://fine-tuning-axolotl/output/qwen_0_5b/`
- `s3://fine-tuning-axolotl/output/qwen_1_5b/`

## Usage

```bash
uv run python examples/parallel_jobs/axolotl_sweep.py
```

The bucket must exist and be mountable as `s3://fine-tuning-axolotl:/workspace/data:rw`. Quota should cover two concurrent H100 jobs.
