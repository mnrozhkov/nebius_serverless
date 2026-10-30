"""A local job recipe. Constructing it does not contact Nebius."""

import uuid
from collections.abc import Mapping, Sequence
from datetime import timedelta
from pathlib import Path
from typing import overload

from .aliases import resolve_machine
from .errors import UnsupportedFeature
from .loop import reject_running_loop
from .profile import load_profile
from .recipe import (
    check_identity,
    describe,
    reject_spot_on_cpu,
    request_body,
    timeout_seconds,
    validate_command,
    validate_disk,
    validate_env,
    validate_image,
    validate_optional_text,
    validate_pricing,
    validate_volumes,
)
from .run import Run
from .transport import Transport, call_transport
from .yaml_job import load_yaml_fields


class Job:
    """Recipe for one ``nebius ai job create``.

    Constructing a ``Job``, loading YAML, or importing the package does
    not authenticate, upload, or create. The Nebius SDK is imported on
    the call that needs a profile or a live create.
    """

    def __init__(
        self,
        command: Sequence[str],
        *,
        image: str,
        gpu: str | None = None,
        platform: str | None = None,
        preset: str | None = None,
        timeout: str | int | float | timedelta,
        pricing: str = "on-demand",
        subnet_id: str | None = None,
        volumes: Sequence[str] | None = None,
        env: Mapping[str, str] | None = None,
        name: str | None = None,
        disk: str | None = None,
        profile: str | None = None,
        project: str | None = None,
    ) -> None:
        self.command = validate_command(command)
        self.image = validate_image(image)
        self.gpu = gpu
        self.platform = validate_optional_text(platform, "platform")
        self.preset = validate_optional_text(preset, "preset")
        check_identity(self.gpu, self.platform, self.preset)
        self.timeout_seconds = timeout_seconds(timeout)
        self.pricing = validate_pricing(pricing)
        reject_spot_on_cpu(self.pricing, self.gpu, self.platform)
        self.subnet_id = validate_optional_text(subnet_id, "subnet_id")
        self.volumes = validate_volumes(volumes)
        self.env = validate_env(env)
        supplied = validate_optional_text(name, "name")
        self.name = supplied or _generated_name()
        self.disk = validate_disk(validate_optional_text(disk, "disk"))
        self.profile = validate_optional_text(profile, "profile")
        self.project = validate_optional_text(project, "project")

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Job":
        """Load a schema-version-1 command document.

        Function documents are rejected. Relative paths inside the
        document are not expanded.
        """
        fields = load_yaml_fields(path)
        return cls(**fields)  # type: ignore[arg-type]

    @overload
    def create(
        self,
        dry_run: bool = False,
        *,
        region: str | None = None,
        project: str | None = None,
        transport: Transport | None = None,
    ) -> Run: ...

    @overload
    def create(
        self,
        dry_run: bool = True,
        *,
        region: str | None = None,
        project: str | None = None,
        transport: Transport | None = None,
    ) -> dict[str, object]: ...

    def create(
        self,
        dry_run: bool = False,
        *,
        region: str | None = None,
        project: str | None = None,
        transport: Transport | None = None,
    ) -> Run | dict[str, object]:
        """Create a cloud job, or return the request when ``dry_run``.

        ``dry_run=True`` resolves project and region and does not call
        create. Region comes from ``region=`` or the profile when either
        names one, otherwise from the project's ``spec.region``. A live
        call returns a ``Run`` after the id is known and does not wait
        for the container to finish. A second call starts another cloud
        job.
        """
        reject_running_loop("create_async")
        return self._create(
            dry_run=dry_run,
            region=region,
            project=project,
            transport=transport,
        )

    async def create_async(
        self,
        dry_run: bool = False,
        *,
        region: str | None = None,
        project: str | None = None,
        transport: Transport | None = None,
    ) -> Run | dict[str, object]:
        """Await the same create as ``create``.

        Cancelling this await does not cancel the cloud job.
        """
        import asyncio

        return await asyncio.to_thread(
            self._create,
            dry_run=dry_run,
            region=region,
            project=project,
            transport=transport,
        )

    def _create(
        self,
        *,
        dry_run: bool,
        region: str | None,
        project: str | None,
        transport: Transport | None,
    ) -> Run | dict[str, object]:
        project_id, region_id = _location(
            profile=self.profile,
            project=project if project is not None else self.project,
            region=region,
        )
        machine = resolve_machine(
            self.gpu,
            self.platform,
            self.preset,
            region_id,
        )
        if self.pricing == "spot" and machine.cpu:
            raise UnsupportedFeature(
                "Spot pricing is not supported on CPU.",
                operation="create",
            )
        description = describe(
            command=self.command,
            image=self.image,
            project=project_id,
            region=region_id,
            platform=machine.platform,
            preset=machine.preset,
            timeout=self.timeout_seconds,
            pricing=self.pricing,
            subnet_id=self.subnet_id,
            volumes=self.volumes,
            env_keys=[key for key, _value in self.env],
            name=self.name,
            disk=self.disk,
        )
        if dry_run:
            return description
        chosen = transport or _sdk_transport(self.profile, project_id)
        body = request_body(
            command=self.command,
            image=self.image,
            project=project_id,
            platform=machine.platform,
            preset=machine.preset,
            timeout=self.timeout_seconds,
            pricing=self.pricing,
            subnet_id=self.subnet_id,
            volumes=self.volumes,
            env=self.env,
            name=self.name,
            disk=self.disk,
        )
        result = call_transport(chosen, body)
        return Run(
            result.resource_id or "",
            name=self.name,
            transport=chosen,
            create_state=result.state,
        )


def _location(
    *,
    profile: str | None,
    project: str | None,
    region: str | None,
) -> tuple[str, str]:
    project_id = project
    region_id = region
    if project_id is None or region_id is None:
        loaded_project, loaded_region = load_profile(profile)
        if project_id is None:
            project_id = loaded_project
        if region_id is None:
            region_id = loaded_region
    if region_id is None:
        from .sdk_transport import project_region

        region_id = project_region(profile, project_id)
    return project_id, region_id


def _sdk_transport(profile: str | None, project: str) -> Transport:
    from .sdk_transport import SdkTransport

    return SdkTransport(profile=profile, project=project)


def _generated_name() -> str:
    return "job-" + uuid.uuid4().hex[:12]
