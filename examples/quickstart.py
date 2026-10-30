"""The README quickstart.

Same recipe as the README: ``["nvidia-smi"]``, ``gpu="h100"``, and
timeout ``1h``. Dry-run is the default. ``--create`` submits, fetches,
waits until the job finishes, and reloads the id with ``jobs.get``.
"""

import argparse

import nebius_serverless as ns

IMAGE = "nvidia/cuda:13.1.1-runtime-ubuntu24.04"


def main() -> None:
    """Create the README job, or print its request."""
    args = _parser().parse_args()
    job = ns.Job(
        ["nvidia-smi"],
        image=IMAGE,
        gpu="h100",
        timeout="1h",
        **_profile_kwargs(args),
    )
    overrides = _create_kwargs(args)
    if not args.create:
        print(job.create(dry_run=True, **overrides))
        return
    run = job.create(**overrides)
    print(run.id)
    record = run.get()
    record = run.wait()
    saved_id = run.id
    loaded = ns.jobs.get(saved_id, **_profile_kwargs(args))
    _require_completed(loaded, record)


def _require_completed(run: ns.Run, record: object) -> None:
    state = run.status
    recorded = _state(record)
    if recorded not in (None, state):
        raise SystemExit(
            f"{run.id} record state {recorded} disagrees with {state}"
        )
    if state != "COMPLETED":
        raise SystemExit(f"{run.id} ended {state}")
    print(state)


def _profile_kwargs(args: argparse.Namespace) -> dict[str, str]:
    chosen = {}
    if args.profile:
        chosen["profile"] = args.profile
    if args.project:
        chosen["project"] = args.project
    return chosen


def _create_kwargs(args: argparse.Namespace) -> dict[str, str]:
    if args.region:
        return {"region": args.region}
    return {}


def _state(record: object) -> str | None:
    if not isinstance(record, dict):
        return None
    status = record.get("status")
    if not isinstance(status, dict):
        return None
    state = status.get("state")
    if isinstance(state, str):
        return state
    return None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the README nvidia-smi quickstart.",
    )
    parser.add_argument(
        "--create",
        action="store_true",
        help="Create the job. The default is a dry run.",
    )
    parser.add_argument("--profile")
    parser.add_argument("--project")
    parser.add_argument(
        "--region",
        help="Region when the active profile does not set one.",
    )
    return parser


if __name__ == "__main__":
    main()
