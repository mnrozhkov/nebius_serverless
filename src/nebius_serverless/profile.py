"""Project and region from the active Nebius SDK profile."""

import re
from pathlib import Path

from .aliases import ALIASES
from .errors import ValidationError

_MISSING = (
    "Project or region configuration is missing or ambiguous."
)

_REGION_IDS = sorted(
    {region for row in ALIASES for region in row.regions},
    key=len,
    reverse=True,
)


def load_profile(
    profile: str | None = None,
    *,
    config_file: str | Path | None = None,
) -> tuple[str, str]:
    """Return ``(project_id, region)`` from the SDK profile.

    A missing or ambiguous project or region raises ``ValidationError``
    before create. The message does not include credential material.
    """
    try:
        from nebius.aio.cli_config import Config
    except ImportError:
        raise ValidationError(
            "The Nebius SDK is required to resolve a profile.",
            operation="create",
        ) from None
    kwargs: dict[str, object] = {"profile": profile}
    if config_file is not None:
        kwargs["config_file"] = config_file
        kwargs["no_env"] = True
    try:
        config = Config(**kwargs)
        project = config.parent_id
    except Exception:
        raise ValidationError(_MISSING, operation="create") from None
    region = _region_of(config)
    if not isinstance(project, str) or project.strip() == "":
        raise ValidationError(_MISSING, operation="create")
    if region is None:
        raise ValidationError(_MISSING, operation="create")
    return project, region


def _region_of(config: object) -> str | None:
    profile = getattr(config, "_profile", {})
    if not isinstance(profile, dict):
        raise ValidationError(_MISSING, operation="create")
    raw = profile.get("region")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    if raw not in (None, ""):
        raise ValidationError(_MISSING, operation="create")
    endpoint = ""
    endpoint_of = getattr(config, "endpoint", None)
    if callable(endpoint_of):
        endpoint = endpoint_of() or ""
    found = [
        region
        for region in _REGION_IDS
        if re.search(
            rf"(?<![a-z0-9]){re.escape(region)}(?![a-z0-9])",
            endpoint,
        )
    ]
    if len(found) > 1:
        raise ValidationError(_MISSING, operation="create")
    if len(found) == 1:
        return found[0]
    return None
