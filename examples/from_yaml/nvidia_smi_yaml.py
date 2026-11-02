"""Run a job recipe loaded from YAML.

``--config`` is the path to the YAML file. The recipe in that file is
the whole configuration. Uses the active Nebius profile.
"""

import typer

import nebius_serverless as ns


def main(
    config: str = typer.Option(
        ...,
        help="Path to the job YAML file.",
    ),
) -> None:
    """Create the job described by --config and wait for it."""
    job = ns.Job.from_yaml(config)
    run = job.create()
    run.wait()
    run.display()
    if run.status != "COMPLETED":
        raise SystemExit(f"{run.id} ended {run.status}")


if __name__ == "__main__":
    typer.run(main)
