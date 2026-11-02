# Fine-tune a Model with Axolotl

Rebuilds the [Nebius Serverless AI Cookbook Axolotl recipe](https://github.com/nebius/serverless-ai-cookbook/blob/main/training/axolotl-finetuning/README.md) with `nebius_serverless`:

- Fine-tunes `Qwen/Qwen2.5-0.5B` with QLoRA (`config.yaml`).
- Runs `docker.io/axolotlai/axolotl:main-20260309-py3.11-cu128-2.9.1` on a spot `h100` job (`500Gi` disk, `24h` timeout).
- Keeps `output_dir: /workspace/output` on the local container disk during training (avoiding S3 mount `unlink` errors on `debug.log`), then copies checkpoints and adapters to the mounted bucket under `/workspace/data/output/$RUN_ID`.

## 1. Upload `config.yaml` to Object Storage

```bash
aws s3 cp examples/finetuning/config.yaml s3://fine-tuning-axolotl/config.yaml \
  --endpoint-url https://storage.eu-north1.nebius.cloud
```

## 2. Run the fine-tuning job

```bash
uv run python examples/finetuning/axolotl-finetuning.py
```

Inspect container logs while running or after completion:

```bash
nebius ai job logs <job-id>
```
