"""GPU and CPU alias table for Nebius public regions."""

from dataclasses import dataclass

from .errors import ValidationError

_PRESET_H100 = "1gpu-16vcpu-200gb"
_PRESET_B300 = "1gpu-24vcpu-346gb"
_PRESET_L40S = "1gpu-8vcpu-32gb"
_PRESET_B200 = "1gpu-20vcpu-224gb"
_PRESET_RTX = "1gpu-24vcpu-218gb"
_PRESET_CPU = "2vcpu-8gb"


@dataclass(frozen=True)
class Alias:
    """One gpu alias row: regions, platform, and minimal preset."""

    gpu: str
    regions: tuple[str, ...]
    platform: str
    preset: str


ALIASES: tuple[Alias, ...] = (
    Alias("h100", ("eu-north1",), "gpu-h100-sxm", _PRESET_H100),
    Alias(
        "h200",
        ("eu-north1", "eu-north2", "eu-west1", "us-central1"),
        "gpu-h200-sxm",
        _PRESET_H100,
    ),
    Alias(
        "b300",
        ("uk-south1", "eu-west2", "us-north1"),
        "gpu-b300-sxm",
        _PRESET_B300,
    ),
    Alias("l40s", ("eu-north1",), "gpu-l40s-a", _PRESET_L40S),
    Alias("b200", ("us-central1",), "gpu-b200-sxm", _PRESET_B200),
    Alias("b200", ("me-west1",), "gpu-b200-sxm-a", _PRESET_B200),
    Alias("rtx", ("us-central1",), "gpu-rtx6000", _PRESET_RTX),
    Alias(
        "rtx",
        ("uk-south2", "eu-south1"),
        "gpu-rtx6000-a",
        _PRESET_RTX,
    ),
)

CPU_PLATFORM = "cpu-d3"
CPU_PRESET = _PRESET_CPU

PRESETS: dict[str, str] = {
    row.platform: row.preset for row in ALIASES
}
PRESETS[CPU_PLATFORM] = CPU_PRESET

KNOWN_GPUS = frozenset(row.gpu for row in ALIASES)


@dataclass(frozen=True)
class Machine:
    """Platform and preset that will be sent on create."""

    platform: str
    preset: str
    cpu: bool


def known_cpu(gpu: str | None, platform: str | None) -> bool:
    """Return whether the recipe is already known to be a CPU machine."""
    if platform is not None:
        return platform == CPU_PLATFORM or platform.startswith("cpu")
    return gpu is None


def validate_gpu_name(gpu: str | None, platform: str | None) -> None:
    """Reject ``gpu='cpu'`` and unknown aliases when no platform is set."""
    if gpu == "cpu":
        raise ValidationError(
            "gpu='cpu' is invalid. Omit gpu for a CPU job.",
            operation="Job",
        )
    if platform is not None or gpu is None:
        return
    if gpu not in KNOWN_GPUS:
        raise ValidationError(
            f"Unknown gpu alias {gpu!r}.",
            operation="Job",
        )


def validate_platform(platform: str | None, preset: str | None) -> None:
    """An unknown platform id requires an explicit preset."""
    if platform is None:
        return
    if platform in PRESETS or preset:
        return
    raise ValidationError(
        f"Unknown platform {platform!r} requires preset.",
        operation="Job",
    )


def resolve_machine(
    gpu: str | None,
    platform: str | None,
    preset: str | None,
    region: str,
) -> Machine:
    """Pick the platform and preset for a region.

    An explicit platform overrides ``gpu``. The region check applies to
    aliases only.
    """
    if platform is not None:
        chosen = preset or PRESETS.get(platform)
        if chosen is None:
            raise ValidationError(
                f"Unknown platform {platform!r} requires preset.",
                operation="create",
            )
        cpu = platform == CPU_PLATFORM or platform.startswith("cpu")
        return Machine(platform, chosen, cpu)
    if gpu is None:
        return Machine(CPU_PLATFORM, preset or CPU_PRESET, True)
    match = _row_for(gpu, region)
    return Machine(match.platform, preset or match.preset, False)


def _row_for(gpu: str, region: str) -> Alias:
    matches = [row for row in ALIASES if row.gpu == gpu]
    for row in matches:
        if region in row.regions:
            return row
    available = sorted(
        {name for row in matches for name in row.regions}
    )
    listed = ", ".join(available)
    raise ValidationError(
        f"gpu {gpu!r} is not available in {region}. "
        f"Available regions: {listed}.",
        operation="create",
    )
