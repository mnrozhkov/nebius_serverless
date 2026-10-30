"""Run a job recipe loaded from YAML.

``--config`` is the path to the YAML file. The recipe in that file is
the whole configuration. Uses the active Nebius profile.
"""

import argparse

import nebius_serverless as ns


def main() -> None:
    """Create the job described by ``--config`` and wait for it."""
    parser = argparse.ArgumentParser(
        description="Run a job recipe loaded from YAML.",
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Path to the job YAML file.",
    )
    args = parser.parse_args()
    job = ns.Job.from_yaml(args.config)
    run = job.create()
    print(run.id)
    run.wait()
    if run.status != "COMPLETED":
        raise SystemExit(f"{run.id} ended {run.status}")


if __name__ == "__main__":
    main()
