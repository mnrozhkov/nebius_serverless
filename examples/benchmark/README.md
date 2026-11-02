# SDK Comparison & Benchmark Suite

This directory holds the multi-provider SDK comparison and benchmark suite alongside the full report in [`sdk-comparison.md`](sdk-comparison.md).

Because this Cloud Jobs slice provides ergonomic Python sugar on top of the Nebius SDK for **containerized command workloads** (while function decorators will be covered separately in a dedicated decorators prototype), the comparison focuses on two real containerized GPU workloads (`job_quickstart.py` and the Axolotl fine-tuning equivalents) rather than inline Python `worker` strings:

- **Quickstart (`nebius_serverless`):** [`../job_quickstart.py`](../job_quickstart.py)
- **Fine-tuning with Axolotl (`nebius_serverless`):** [`../train/axolotl_lora.py`](../train/axolotl_lora.py)

## Directory Layout

- **[`sdk-comparison.md`](sdk-comparison.md)** — 6-panel SDK comparison report with side-by-side orchestration excerpts, setup requirements, line-count reductions, and frozen SHA-256 file snapshots.
- **[`nebius/`](nebius/)** — Official Nebius Python SDK (`nebius==0.6.27`) baseline scripts (`quickstart.py` and `axolotl_lora.py`; see [`nebius/README.md`](nebius/README.md)).
- **[`modal/`](modal/)** — Isolated Modal (`modal==1.6.3`) comparison project (`quickstart.py` and `axolotl_lora.py`; see [`modal/README.md`](modal/README.md)).
- **[`runpod/`](runpod/)** — Isolated RunPod (`runpod==2.0.0rc1`) comparison project (`quickstart.py` and `axolotl_lora.py`; see [`runpod/README.md`](runpod/README.md)).
- **[`measure.py`](measure.py)** — Reproducible line-count and SHA-256 hash calculator across all 8 task variants.

## Computing Line Counts and SHA-256 Hashes

```bash
uv run python examples/benchmark/measure.py
uv run python examples/benchmark/measure.py --json
```
