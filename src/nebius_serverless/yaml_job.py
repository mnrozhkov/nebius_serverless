"""Strict loader for schema-version-1 command documents."""

from collections.abc import Mapping
from pathlib import Path

import yaml
from yaml.events import (
    AliasEvent,
    MappingStartEvent,
    ScalarEvent,
    SequenceStartEvent,
)

from .errors import UnsupportedFeature, ValidationError

_LIMIT = 1024 * 1024
_ALLOWED = frozenset(
    {
        "schema_version",
        "kind",
        "image",
        "command",
        "gpu",
        "platform",
        "preset",
        "timeout",
        "pricing",
        "subnet_id",
        "volumes",
        "env",
        "name",
        "disk",
    }
)
_PLAIN_TAGS = frozenset(
    {
        "tag:yaml.org,2002:str",
        "tag:yaml.org,2002:int",
        "tag:yaml.org,2002:float",
        "tag:yaml.org,2002:bool",
        "tag:yaml.org,2002:null",
        "tag:yaml.org,2002:seq",
        "tag:yaml.org,2002:map",
    }
)


class _StrictLoader(yaml.SafeLoader):
    """Safe loader that rejects aliases, anchors, tags, and duplicates."""

    def compose_node(self, parent, index):  # type: ignore[no-untyped-def]
        if self.check_event(AliasEvent):
            raise ValidationError(
                "YAML aliases are rejected.",
                operation="from_yaml",
            )
        event = self.peek_event()
        if getattr(event, "anchor", None):
            raise ValidationError(
                "YAML anchors are rejected.",
                operation="from_yaml",
            )
        if _explicit_tag(event):
            raise ValidationError(
                "YAML tags are rejected.",
                operation="from_yaml",
            )
        return super().compose_node(parent, index)

    def construct_mapping(self, node, deep=False):  # type: ignore[no-untyped-def]
        mapping: dict[object, object] = {}
        for key_node, value_node in node.value:
            if key_node.tag == "tag:yaml.org,2002:merge":
                raise ValidationError(
                    "YAML merge keys are rejected.",
                    operation="from_yaml",
                )
            key = self.construct_object(key_node, deep=deep)
            if key == "<<":
                raise ValidationError(
                    "YAML merge keys are rejected.",
                    operation="from_yaml",
                )
            if key in mapping:
                raise ValidationError(
                    f"Duplicate YAML key {key!r}.",
                    operation="from_yaml",
                )
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def _explicit_tag(event: object) -> bool:
    if not isinstance(
        event,
        (ScalarEvent, SequenceStartEvent, MappingStartEvent),
    ):
        return False
    tag = event.tag
    if tag is None or tag in _PLAIN_TAGS and _implicit(event):
        return False
    if tag not in _PLAIN_TAGS:
        return True
    return not _implicit(event)


def _implicit(
    event: ScalarEvent | SequenceStartEvent | MappingStartEvent,
) -> bool:
    implicit = getattr(event, "implicit", True)
    if isinstance(implicit, tuple):
        return any(implicit)
    return bool(implicit)


def load_yaml_fields(path: str | Path) -> dict[str, object]:
    """Read one command document into ``Job`` constructor arguments.

    Relative strings inside the document are not expanded. A document
    over 1 MiB is rejected before it is parsed.
    """
    source = Path(path)
    try:
        data = source.read_bytes()
    except OSError:
        raise ValidationError(
            "The YAML document was rejected.",
            operation="from_yaml",
        ) from None
    if len(data) > _LIMIT:
        raise ValidationError(
            "The YAML document is over 1 MiB.",
            operation="from_yaml",
        )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise ValidationError(
            "The YAML document was rejected.",
            operation="from_yaml",
        ) from None
    try:
        document = yaml.load(text, Loader=_StrictLoader)
    except ValidationError:
        raise
    except Exception:
        raise ValidationError(
            "The YAML document was rejected.",
            operation="from_yaml",
        ) from None
    if not isinstance(document, dict):
        raise ValidationError(
            "The YAML document must be a mapping.",
            operation="from_yaml",
        )
    return _fields(document)


def _fields(document: Mapping[object, object]) -> dict[str, object]:
    if (
        document.get("kind") == "function"
        or document.get("execution") == "function"
    ):
        raise UnsupportedFeature(
            "Function YAML is not supported. Use Job.create().",
            operation="from_yaml",
        )
    unknown = sorted(
        str(key) for key in document if key not in _ALLOWED
    )
    if unknown:
        names = ", ".join(unknown)
        raise ValidationError(
            f"Unknown YAML keys: {names}.",
            operation="from_yaml",
        )
    if document.get("schema_version") != 1:
        raise ValidationError(
            "schema_version must be 1.",
            operation="from_yaml",
        )
    if document.get("kind") != "job":
        raise ValidationError(
            "kind must be job.",
            operation="from_yaml",
        )
    fields: dict[str, object] = {
        "command": document.get("command"),
        "image": document.get("image"),
        "timeout": document.get("timeout"),
    }
    for name in (
        "gpu",
        "platform",
        "preset",
        "pricing",
        "subnet_id",
        "volumes",
        "env",
        "name",
        "disk",
    ):
        if name in document and document[name] is not None:
            fields[name] = document[name]
    return fields
