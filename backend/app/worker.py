"""Run separately: python -m app.worker. No automatic paid graph replay."""

import asyncio
import logging
import signal
from typing import Any
from supabase import AsyncClient
from contextlib import suppress

from app.agents.graph import build_graph
from app.agents.nodes.fetcher import RetrievalFailure
from app.core.config import settings
from app.db import get_supabase
from app.services.execution import execution
from app.services.jobs import Lease, LostLease, rpc

logger = logging.getLogger(__name__)


async def run_claim(db: AsyncClient, job: dict[str, Any]) -> None:
    lease = Lease(db, job)

    async def work() -> None:
        await lease.heartbeat()
        if job["state"] == "finalizing":
            # Immutable saved output; never construct/invoke the paid graph.
            await lease.call("publish_analysis")
            return
        options = job["execution_inputs"]
        if options.get("version") != 1:
            await lease.call(
                "fail_analysis",
                p_error="Unsupported saved execution version. Operator action is required; no providers were called.",
            )
            return
        token = execution.set((lease, options))
        try:
            initial = dict(
                search_id=job["search_id"],
                lease_token=job["lease_token"],
                **job["payload"],
                search_queries=[],
                raw_patents=[],
                deduped_patents=[],
                clusters=[],
                white_space_analysis="",
                final_report="",
                errors=[],
                citation_links=[],
                retrieval_outcome="complete",
                coverage_warnings=[]
            )
            try:
                final = await asyncio.wait_for(
                    build_graph(db).ainvoke(initial),
                    settings.worker_execution_timeout_seconds,
                )
            except LostLease:
                raise
            except Exception as exc:
                message = (
                    str(exc)
                    if isinstance(exc, RetrievalFailure)
                    else "Analysis execution failed. Usage is retained. A fresh analysis consumes new usage."
                )
                await lease.call("fail_analysis", p_error=message)
                return
            # If either response is uncertain, leave the durable state alone.
            # A lost checkpoint response must NEVER turn into failure/re-execution.
            await lease.call(
                "checkpoint_analysis",
                p_output={
                    "result": {
                        key: final.get(key)
                        for key in (
                            "clusters",
                            "white_space_analysis",
                            "final_report",
                            "citation_links",
                            "retrieval_outcome",
                            "coverage_warnings",
                        )
                    },
                    "patents": final["deduped_patents"],
                },
            )
            await lease.call("publish_analysis")
        finally:
            execution.reset(token)

    async def keep_alive() -> None:
        while True:
            await asyncio.sleep(settings.worker_heartbeat_seconds)
            await lease.heartbeat()

    task = asyncio.create_task(work())
    heartbeat = asyncio.create_task(keep_alive())
    try:
        done, _ = await asyncio.wait(
            (task, heartbeat), return_when=asyncio.FIRST_COMPLETED
        )
        for completed in done:
            await completed
    except LostLease:
        logger.warning(
            "Stopped job %s: lease or database confirmation lost", job["search_id"]
        )
    finally:
        task.cancel()
        heartbeat.cancel()
        await asyncio.gather(task, heartbeat, return_exceptions=True)


async def serve(stop: asyncio.Event | None = None) -> None:
    stop = stop or asyncio.Event()
    db = await get_supabase()
    tasks: set[asyncio.Task[None]] = set()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    try:
        while not stop.is_set():
            for task in list(tasks):
                if task.done():
                    tasks.remove(task)
                    try:
                        task.result()
                    except Exception:
                        logger.exception(
                            "Worker task stopped; recovery follows its durable state"
                        )
            if len(tasks) < settings.worker_concurrency:
                try:
                    job = await rpc(
                        db,
                        "claim_analysis",
                        {
                            "p_lease_seconds": settings.worker_lease_seconds,
                            "p_max_active": settings.worker_max_active,
                        },
                    )
                    if job:
                        tasks.add(asyncio.create_task(run_claim(db, job)))
                        continue
                except Exception:
                    logger.warning("Queue unavailable; no new work launched")
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop.wait(), settings.worker_poll_seconds)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve())
