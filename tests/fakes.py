"""In-memory transport and clock for tests."""

import copy
from collections.abc import Mapping

from nebius_serverless.transport import CreateResult


class FakeTransport:
    """Records create, get, and cancel. Does not contact Nebius."""

    def __init__(self) -> None:
        self.bodies: list[dict[str, object]] = []
        self.gets: list[str] = []
        self.cancels: list[str] = []
        self.drop_id = False
        self.failure: str | None = None
        self.conflict_id: str | None = None
        self.state: str | None = "PROVISIONING"
        self.states = ["RUNNING"]
        self._n = 0
        self._get_i = 0

    def create(self, body: Mapping[str, object]) -> CreateResult:
        self.bodies.append(copy.deepcopy(dict(body)))
        self._n += 1
        if self.failure is not None:
            return CreateResult(
                accepted=False,
                failure=self.failure,
                conflict_id=self.conflict_id,
            )
        if self.drop_id:
            return CreateResult(accepted=True, resource_id=None)
        return CreateResult(
            resource_id=f"job-{self._n}",
            accepted=True,
            state=self.state,
        )

    def get(self, job_id: str) -> dict[str, object]:
        self.gets.append(job_id)
        index = min(self._get_i, len(self.states) - 1)
        self._get_i += 1
        return {
            "metadata": {"id": job_id, "name": "saved"},
            "status": {"state": self.states[index]},
            "spec": {"image": "python:3.12-slim"},
        }

    def cancel(self, job_id: str) -> dict[str, object]:
        self.cancels.append(job_id)
        return {"id": job_id, "accepted": True}


class FakeClock:
    """Monotonic clock that advances only when sleep is called."""

    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds
