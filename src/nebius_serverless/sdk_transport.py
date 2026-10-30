"""Nebius Python SDK adapter for create, get, and cancel.

Imported on the call that needs it. ``Job()`` does not import this module.
"""

import atexit
import json
from collections.abc import Mapping
from datetime import timedelta

from .errors import (
    AccessError,
    CapacityError,
    SubmissionUncertain,
    TransportError,
)
from .recipe import disk_bytes
from .transport import CreateResult

_USER_AGENT = "nebius-serverless/0.0.1"
_DEFINITE = frozenset(
    {
        "INVALID_ARGUMENT",
        "NOT_FOUND",
        "FAILED_PRECONDITION",
        "OUT_OF_RANGE",
        "UNIMPLEMENTED",
        "CANCELLED",
    }
)


class SdkTransport:
    """Create, get, and cancel through ``JobServiceClient``.

    The client does not shell out to the ``nebius`` binary and does not
    hand-roll REST. One SDK instance is kept for later get and cancel.
    """

    def __init__(self, profile: str | None, project: str | None) -> None:
        self._profile = profile
        self._project = project
        self._sdk: object | None = None

    def create(self, body: Mapping[str, object]) -> CreateResult:
        """Create once and wait until the operation has a resource id."""
        try:
            from nebius.aio.service_error import RequestError
        except ImportError:
            raise TransportError(
                "The Nebius SDK is required to create a job.",
                operation="create",
            ) from None
        try:
            operation = self._client().create(
                build_create_request(body)
            ).wait()
        except RequestError as exc:
            return _from_request(exc, sent=False)
        except Exception:
            return CreateResult(accepted=False, failure="transport")
        try:
            operation.sync_wait()
        except RequestError as exc:
            if _resource_id(operation):
                return CreateResult(
                    resource_id=_resource_id(operation),
                    accepted=True,
                )
            return _from_request(exc, sent=True)
        except Exception:
            if _resource_id(operation):
                return CreateResult(
                    resource_id=_resource_id(operation),
                    accepted=True,
                )
            return CreateResult(accepted=True, failure="uncertain")
        resource_id = _resource_id(operation)
        if not resource_id:
            return CreateResult(accepted=True, failure="uncertain")
        return CreateResult(resource_id=resource_id, accepted=True)

    def get(self, job_id: str) -> dict[str, object]:
        """Fetch one job and return its JSON object."""
        try:
            from nebius.aio.service_error import RequestError
            from nebius.api.nebius.ai.v1 import GetJobRequest
        except ImportError:
            raise TransportError(
                "The Nebius SDK is required to get a job.",
                operation="get",
                run_id=job_id,
            ) from None
        try:
            job = self._client().get(GetJobRequest(id=job_id)).wait()
        except RequestError as exc:
            _raise_call(exc, operation="get", job_id=job_id)
        except Exception:
            raise TransportError(
                "The get call failed.",
                operation="get",
                run_id=job_id,
            ) from None
        payload = json.loads(
            job.to_json(preserving_proto_field_name=True)
        )
        if not isinstance(payload, dict):
            raise TransportError(
                "The get call failed.",
                operation="get",
                run_id=job_id,
            )
        return payload

    def cancel(self, job_id: str) -> dict[str, object]:
        """Ask Nebius to cancel. Return when the request is accepted."""
        try:
            from nebius.aio.service_error import RequestError
            from nebius.api.nebius.ai.v1 import CancelJobRequest
        except ImportError:
            raise TransportError(
                "The Nebius SDK is required to cancel a job.",
                operation="cancel",
                run_id=job_id,
            ) from None
        try:
            operation = self._client().cancel(
                CancelJobRequest(id=job_id)
            ).wait()
            operation.sync_wait()
        except RequestError as exc:
            _raise_call(exc, operation="cancel", job_id=job_id)
        except Exception:
            raise TransportError(
                "The cancel call failed.",
                operation="cancel",
                run_id=job_id,
            ) from None
        return {
            "id": job_id,
            "resource_id": _resource_id(operation) or job_id,
        }

    def _client(self) -> object:
        if self._sdk is None:
            from nebius.aio.cli_config import Config
            from nebius.sdk import SDK

            kwargs: dict[str, object] = {
                "config_reader": Config(profile=self._profile),
                "user_agent_prefix": _USER_AGENT,
            }
            if self._project:
                kwargs["parent_id"] = self._project
            sdk = SDK(**kwargs)
            atexit.register(sdk.sync_close)
            self._sdk = sdk
        from nebius.api.nebius.ai.v1 import JobServiceClient

        return JobServiceClient(self._sdk)


def build_create_request(body: Mapping[str, object]) -> object:
    """Turn the mapped body into ``CreateJobRequest``."""
    from nebius.api.nebius.ai.v1 import (
        CreateJobRequest,
        FollowsSpotPriceSpec,
        JobSpec,
        PricingModelSpec,
    )
    from nebius.api.nebius.common.v1 import ResourceMetadata
    from nebius.api.nebius.compute.v1 import DiskSpec as ComputeDisk

    metadata = body["metadata"]
    spec = body["spec"]
    if not isinstance(metadata, Mapping) or not isinstance(spec, Mapping):
        raise TransportError(
            "The call failed before create was accepted.",
            operation="create",
        )
    disk = spec["disk"]
    if not isinstance(disk, str):
        raise TransportError(
            "The call failed before create was accepted.",
            operation="create",
        )
    spec_kwargs: dict[str, object] = {
        "image": spec["image"],
        "container_command": spec["container_command"],
        "platform": spec["platform"],
        "preset": spec["preset"],
        "timeout": timedelta(seconds=float(spec["timeout_seconds"])),
        "shm_size_bytes": spec["shm_size_bytes"],
        "disk": JobSpec.DiskSpec(
            type=ComputeDisk.DiskType.NETWORK_SSD,
            size_bytes=disk_bytes(disk),
        ),
    }
    if "args" in spec:
        spec_kwargs["args"] = spec["args"]
    if "subnet_id" in spec:
        spec_kwargs["subnet_id"] = spec["subnet_id"]
    if spec.get("preemptible") is True:
        spec_kwargs["preemptible"] = True
        spec_kwargs["pricing_model"] = PricingModelSpec(
            follows_spot_price=FollowsSpotPriceSpec(),
        )
    variables = spec.get("environment_variables")
    if isinstance(variables, list) and variables:
        spec_kwargs["environment_variables"] = [
            JobSpec.EnvironmentVariable(
                name=item["name"],
                value=item["value"],
            )
            for item in variables
            if isinstance(item, Mapping)
        ]
    mounts = spec.get("volumes")
    if isinstance(mounts, list) and mounts:
        spec_kwargs["volumes"] = [
            _mount(item) for item in mounts if isinstance(item, Mapping)
        ]
    return CreateJobRequest(
        metadata=ResourceMetadata(
            parent_id=str(metadata["parent_id"]),
            name=str(metadata["name"]),
        ),
        spec=JobSpec(**spec_kwargs),
    )


def _mount(item: Mapping[str, object]) -> object:
    from nebius.api.nebius.ai.v1 import JobSpec

    mode = item.get("mode", "rw")
    selected = (
        JobSpec.VolumeMount.Mode.READ_ONLY
        if mode == "ro"
        else JobSpec.VolumeMount.Mode.READ_WRITE
    )
    return JobSpec.VolumeMount(
        source=str(item["source"]),
        container_path=str(item["container_path"]),
        mode=selected,
    )


def classify_code(
    code: str,
    *,
    sent: bool,
    conflict_id: str | None,
    capacity: bool,
    access: bool,
) -> CreateResult:
    """Map one SDK status onto a create result. The text is dropped."""
    if access or code in {"UNAUTHENTICATED", "PERMISSION_DENIED"}:
        return CreateResult(accepted=False, failure="access")
    if capacity or code == "RESOURCE_EXHAUSTED":
        return CreateResult(accepted=False, failure="capacity")
    if code == "ALREADY_EXISTS":
        return CreateResult(
            accepted=True,
            failure="conflict",
            conflict_id=conflict_id,
        )
    if sent and code not in _DEFINITE:
        return CreateResult(accepted=True, failure="uncertain")
    return CreateResult(accepted=False, failure="transport")


def _from_request(exc: object, *, sent: bool) -> CreateResult:
    status = getattr(exc, "status", None)
    code = getattr(getattr(status, "code", None), "name", "")
    errors = getattr(status, "service_errors", ()) or ()
    return classify_code(
        str(code),
        sent=sent,
        conflict_id=_conflict_id(errors),
        capacity=_has_detail(
            errors,
            ("not_enough_resources", "quota_failure"),
        ),
        access=_has_detail(errors, ("permission_denied",)),
    )


def _has_detail(errors: object, names: tuple[str, ...]) -> bool:
    for error in errors:  # type: ignore[union-attr]
        for name in names:
            if getattr(error, name, None) is not None:
                return True
    return False


def _conflict_id(errors: object) -> str | None:
    for error in errors:  # type: ignore[union-attr]
        for name in ("resource_already_exists", "resource_conflict"):
            detail = getattr(error, name, None)
            resource_id = getattr(detail, "resource_id", None)
            if isinstance(resource_id, str) and resource_id:
                return resource_id
    return None


def _raise_call(exc: object, *, operation: str, job_id: str) -> None:
    result = _from_request(exc, sent=True)
    if result.failure == "access":
        raise AccessError(
            "Authentication or permission failed.",
            operation=operation,
            run_id=job_id,
        ) from None
    if result.failure == "capacity":
        raise CapacityError(
            "The API rejected the job for quota or capacity.",
            operation=operation,
            run_id=job_id,
        ) from None
    if result.failure == "uncertain":
        raise SubmissionUncertain(
            "Create may have been accepted and the id is unknown.",
            operation=operation,
            run_id=job_id,
        ) from None
    raise TransportError(
        "The call failed.",
        operation=operation,
        run_id=job_id,
    ) from None


def _resource_id(operation: object) -> str | None:
    resource_id = getattr(operation, "resource_id", None)
    if isinstance(resource_id, str) and resource_id:
        return resource_id
    return None
