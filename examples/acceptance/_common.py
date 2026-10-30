"""Shared argument handling for the acceptance scripts."""

import argparse


def require_completed(run, record) -> None:
    """Exit unless the job reached the successful terminal state."""
    state = run.status
    recorded = _recorded_state(record)
    if recorded not in (None, state):
        raise SystemExit(
            f"{run.id} record state {recorded} disagrees with {state}"
        )
    if state != "COMPLETED":
        raise SystemExit(f"{run.id} ended {state}")


def profile_kwargs(args: argparse.Namespace) -> dict[str, object]:
    """Return the profile and project overrides that were passed."""
    chosen = {}
    if args.profile:
        chosen["profile"] = args.profile
    if args.project:
        chosen["project"] = args.project
    return chosen


def add_run_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the create flag and the profile overrides."""
    parser.add_argument(
        "--create",
        action="store_true",
        help="Create the job. The default is a dry run.",
    )
    parser.add_argument("--profile")
    parser.add_argument("--project")


def add_job_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the shared flags, including the GPU alias."""
    add_run_arguments(parser)
    parser.add_argument("--gpu", default="h100")


def _recorded_state(record):
    if not isinstance(record, dict):
        return None
    status = record.get("status", {})
    if not isinstance(status, dict):
        return None
    return status.get("state")
