"""Awaited twins and the sync-in-loop guard."""

import asyncio
import threading

import pytest
from fakes import FakeTransport

import nebius_serverless as ns


def _job() -> ns.Job:
    return ns.Job(
        ["nvidia-smi"],
        image="python:3.12-slim",
        gpu="h100",
        timeout="1h",
    )


def test_sync_call_inside_a_loop_names_the_twin() -> None:
    job = _job()

    async def create() -> None:
        job.create(dry_run=True, region="eu-north1", project="p")

    with pytest.raises(ns.ValidationError, match="create_async"):
        asyncio.run(create())


def test_awaited_twins_match_the_sync_calls() -> None:
    job = _job()
    sync = job.create(dry_run=True, region="eu-north1", project="p")

    async def once() -> dict[str, object]:
        described = await job.create_async(
            dry_run=True,
            region="eu-north1",
            project="p",
        )
        assert isinstance(described, dict)
        return described

    assert asyncio.run(once()) == sync


def test_async_get_wait_and_cancel() -> None:
    fake = FakeTransport()
    fake.states = ["RUNNING", "COMPLETED"]
    run = _job().create(
        region="eu-north1",
        project="p",
        transport=fake,
    )
    assert isinstance(run, ns.Run)

    async def follow() -> None:
        first = await run.get_async()
        assert first["status"] == {"state": "RUNNING"}
        finished = await run.wait_async(timeout=0)
        assert finished["status"] == {"state": "COMPLETED"}
        payload = await run.cancel_async()
        assert payload["accepted"] is True
        loaded = await ns.jobs.get_async(run.id, transport=fake)
        assert loaded.id == run.id

    asyncio.run(follow())
    assert fake.cancels == [run.id]


def test_cancelling_wait_does_not_cancel_the_job() -> None:
    fake = FakeTransport()
    started = threading.Event()
    release = threading.Event()

    def blocking_get(job_id: str) -> dict[str, object]:
        started.set()
        release.wait(5)
        return {
            "metadata": {"id": job_id},
            "status": {"state": "RUNNING"},
        }

    fake.get = blocking_get  # type: ignore[method-assign]
    run = _job().create(
        region="eu-north1",
        project="p",
        transport=fake,
    )
    assert isinstance(run, ns.Run)

    async def cancel_wait() -> None:
        task = asyncio.create_task(run.wait_async(timeout=0))
        await asyncio.to_thread(started.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel_wait())
    release.set()
    assert fake.cancels == []
