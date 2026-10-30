"""Validate a job recipe and map it to a create request."""

import re
import shlex
from collections.abc import Mapping, Sequence
from datetime import timedelta

from .aliases import known_cpu, validate_gpu_name, validate_platform
from .errors import UnsupportedFeature, ValidationError

MIN_TIMEOUT = 3600
MAX_TIMEOUT = 168 * 3600
DISK_DEFAULT = "250Gi"
SHM_LABEL = "16Gi"
SHM_BYTES = 16 * 1024**3

_IMAGE = re.compile(
    r"^[a-z0-9][a-z0-9._/-]*"
    r"(?::[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}"
    r"|@sha256:[0-9a-f]{64})$"
)
_DURATION = re.compile(r"^(?:([0-9]+)h)?(?:([0-9]+)m)?(?:([0-9]+)s)?$")
_NUMBER = re.compile(r"^[0-9]+(?:\.[0-9]+)?$")
_DISK = re.compile(r"^([0-9]+)(Ki|Mi|Gi|Ti|K|M|G|T)?$")
_S3_VOLUME = re.compile(
    r"^s3://([^/:]+):(/[^:\s]+)(?::(ro|rw)(?::([^:\s]+))?)?$"
)
_MOUNT = re.compile(r"^([^:\s]+):(/[^:\s]+)(?::(ro|rw))?$")
_UNITS = {
    "Ki": 1024,
    "Mi": 1024**2,
    "Gi": 1024**3,
    "Ti": 1024**4,
    "K": 1000,
    "M": 1000**2,
    "G": 1000**3,
    "T": 1000**4,
}


def validate_command(command: object) -> tuple[str, ...]:
    """Return a nonempty command list. A shell string is rejected."""
    if isinstance(command, str) or not isinstance(command, Sequence):
        raise ValidationError(
            "command must be a nonempty list of strings, "
            "not a shell string.",
            operation="Job",
        )
    if len(command) == 0:
        raise ValidationError(
            "command must be a nonempty list of strings.",
            operation="Job",
        )
    parts: list[str] = []
    for item in command:
        if not isinstance(item, str) or item == "":
            raise ValidationError(
                "command must be a nonempty list of strings, "
                "not a shell string.",
                operation="Job",
            )
        parts.append(item)
    return tuple(parts)


def quoted_args(command: Sequence[str]) -> str | None:
    """POSIX-quote every argument after the executable."""
    if len(command) < 2:
        return None
    return " ".join(shlex.quote(part) for part in command[1:])


def validate_image(image: object) -> str:
    """Accept a tag or a sha256 digest and return it unchanged."""
    if not isinstance(image, str) or _IMAGE.fullmatch(image) is None:
        raise ValidationError(
            "image must be registry/path:tag or "
            "registry/path@sha256:<64 hex>.",
            operation="Job",
        )
    return image


def timeout_seconds(timeout: object) -> int | float:
    """Normalize a duration to seconds. Do not round or clamp."""
    if isinstance(timeout, bool):
        seconds: int | float | None = None
    elif isinstance(timeout, timedelta):
        seconds = timeout.total_seconds()
    elif isinstance(timeout, (int, float)):
        seconds = timeout
    elif isinstance(timeout, str):
        seconds = _parse_duration(timeout)
    else:
        seconds = None
    if seconds is None:
        raise ValidationError(
            "timeout must be a duration string, seconds, or timedelta.",
            operation="Job",
        )
    if isinstance(seconds, float) and seconds == int(seconds):
        seconds = int(seconds)
    if seconds < MIN_TIMEOUT or seconds > MAX_TIMEOUT:
        raise ValidationError(
            "timeout must be between 1 hour and 168 hours "
            f"({seconds} seconds).",
            operation="Job",
        )
    return seconds


def _parse_duration(value: str) -> int | float | None:
    match = _DURATION.fullmatch(value)
    if match is not None and any(match.groups()):
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        seconds = int(match.group(3) or 0)
        return hours * 3600 + minutes * 60 + seconds
    if _NUMBER.fullmatch(value) is None:
        return None
    if "." in value:
        return float(value)
    return int(value)


def validate_pricing(pricing: object) -> str:
    """Accept on-demand or spot."""
    if pricing not in ("on-demand", "spot"):
        raise ValidationError(
            "pricing must be 'on-demand' or 'spot'.",
            operation="Job",
        )
    return pricing


def reject_spot_on_cpu(
    pricing: str,
    gpu: str | None,
    platform: str | None,
) -> None:
    """Spot on a known CPU machine is outside this slice."""
    if pricing == "spot" and known_cpu(gpu, platform):
        raise UnsupportedFeature(
            "Spot pricing is not supported on CPU.",
            operation="Job",
        )


def validate_optional_text(value: object, field: str) -> str | None:
    """Return a nonempty string, or None when the field was omitted."""
    if value is None:
        return None
    if not isinstance(value, str) or value == "":
        raise ValidationError(
            f"{field} must be a nonempty string.",
            operation="Job",
        )
    return value


def disk_bytes(disk: str) -> int:
    """Parse a CLI disk size such as ``500Gi`` into bytes."""
    match = _DISK.fullmatch(disk)
    if match is None:
        raise ValidationError(
            "disk must be an integer size with an optional unit, "
            "such as 500Gi.",
            operation="Job",
        )
    amount = int(match.group(1))
    unit = match.group(2)
    scale = 1 if unit is None else _UNITS[unit]
    return amount * scale


def validate_disk(disk: str | None) -> str | None:
    """Pass a disk string through after checking it parses."""
    if disk is None:
        return None
    disk_bytes(disk)
    return disk


def validate_volumes(volumes: object) -> tuple[str, ...]:
    """Pass volume strings through. Objects are not looked up."""
    if volumes is None:
        return ()
    if isinstance(volumes, str) or not isinstance(volumes, Sequence):
        raise ValidationError(
            "volumes must be a list of mount strings.",
            operation="Job",
        )
    checked: list[str] = []
    for item in volumes:
        if not isinstance(item, str) or not _volume_ok(item):
            raise ValidationError(
                "volumes must be source:container_path[:mode] or "
                "s3://bucket:/container_path[:mode[:profile]].",
                operation="Job",
            )
        checked.append(item)
    return tuple(checked)


def _volume_ok(item: str) -> bool:
    return (
        _S3_VOLUME.fullmatch(item) is not None
        or _MOUNT.fullmatch(item) is not None
    )


def parse_volume(item: str) -> dict[str, str]:
    """Split one volume string into source, path, and mode."""
    s3_match = _S3_VOLUME.fullmatch(item)
    if s3_match is not None:
        parsed = {
            "source": f"s3://{s3_match.group(1)}",
            "container_path": s3_match.group(2),
            "mode": s3_match.group(3) or "rw",
        }
        profile = s3_match.group(4)
        if profile:
            parsed["profile"] = profile
        return parsed
    mount = _MOUNT.fullmatch(item)
    if mount is None:
        raise ValidationError(
            "volumes must be source:container_path[:mode] or "
            "s3://bucket:/container_path[:mode[:profile]].",
            operation="Job",
        )
    return {
        "source": mount.group(1),
        "container_path": mount.group(2),
        "mode": mount.group(3) or "rw",
    }


def validate_env(env: object) -> tuple[tuple[str, str], ...]:
    """Copy env pairs. Values stay on the recipe and off the plan."""
    if env is None:
        return ()
    if not isinstance(env, Mapping):
        raise ValidationError(
            "env must be a dict of strings.",
            operation="Job",
        )
    pairs: list[tuple[str, str]] = []
    for key, value in env.items():
        if not isinstance(key, str) or key == "":
            raise ValidationError(
                "env keys must be nonempty strings.",
                operation="Job",
            )
        if not isinstance(value, str):
            raise ValidationError(
                "env values must be strings.",
                operation="Job",
            )
        pairs.append((key, value))
    return tuple(pairs)


def check_identity(
    gpu: str | None,
    platform: str | None,
    preset: str | None,
) -> None:
    """Validate alias names and the platform/preset pair."""
    validate_gpu_name(gpu, platform)
    validate_platform(platform, preset)


def describe(
    *,
    command: Sequence[str],
    image: str,
    project: str,
    region: str,
    platform: str,
    preset: str,
    timeout: int | float,
    pricing: str,
    subnet_id: str | None,
    volumes: Sequence[str],
    env_keys: Sequence[str],
    name: str,
    disk: str | None,
) -> dict[str, object]:
    """Build the dry-run description. Env values are not included."""
    description: dict[str, object] = {
        "image": image,
        "command": list(command),
    }
    args = quoted_args(command)
    if args is not None:
        description["args"] = args
    description["project"] = project
    description["region"] = region
    description["platform"] = platform
    description["preset"] = preset
    description["timeout"] = timeout
    description["pricing"] = pricing
    if subnet_id is not None:
        description["subnet_id"] = subnet_id
    if volumes:
        description["volumes"] = list(volumes)
    description["env"] = list(env_keys)
    description["name"] = name
    description["disk"] = disk if disk is not None else DISK_DEFAULT
    description["shm"] = SHM_LABEL
    return description


def request_body(
    *,
    command: Sequence[str],
    image: str,
    project: str,
    platform: str,
    preset: str,
    timeout: int | float,
    pricing: str,
    subnet_id: str | None,
    volumes: Sequence[str],
    env: Sequence[tuple[str, str]],
    name: str,
    disk: str | None,
) -> dict[str, object]:
    """Map a recipe to the create body the transport sends."""
    spec: dict[str, object] = {
        "image": image,
        "container_command": command[0],
        "platform": platform,
        "preset": preset,
        "timeout_seconds": timeout,
        "disk": disk if disk is not None else DISK_DEFAULT,
        "shm_size_bytes": SHM_BYTES,
    }
    args = quoted_args(command)
    if args is not None:
        spec["args"] = args
    if subnet_id is not None:
        spec["subnet_id"] = subnet_id
    if volumes:
        spec["volumes"] = [parse_volume(item) for item in volumes]
    if env:
        spec["environment_variables"] = [
            {"name": key, "value": value} for key, value in env
        ]
    if pricing == "spot":
        spec["preemptible"] = True
        spec["follows_spot_price"] = True
    return {
        "metadata": {"parent_id": project, "name": name},
        "spec": spec,
    }
