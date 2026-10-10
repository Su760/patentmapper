"""Real process kill/restart, database persistence and mocked paid execution."""

import asyncio
import os
from pathlib import Path
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import test_durable_jobs_sql as queue
from app.worker import run_claim
from app.services.execution import execution, before_paid_call
from app.services.jobs import Lease, LostLease
from app.core.config import settings
from test_saved_results import claim, state


class DurableWorkerProcessTest(unittest.IsolatedAsyncioTestCase):
    setUpClass = classmethod(queue.DurableJobsSQLTest.setUpClass.__func__)
    rpc = queue.DurableJobsSQLTest.rpc
    def admit(self, **kwargs):
        return queue.DurableJobsSQLTest.admit(self, version=2, **kwargs)
    expire = queue.DurableJobsSQLTest.expire

    def setUp(self):
        queue.DurableJobsSQLTest.setUp(self)
        self.sql.run(
            "CREATE TABLE IF NOT EXISTS public.worker_probe(event text); TRUNCATE public.worker_probe"
        )

    def launch(self, mode=""):
        backend = Path(__file__).resolve().parents[1]
        env = {
            **os.environ,
            "PYTHONPATH": str(backend),
            "FIXTURE_STOP_AT": mode,
            "WORKER_CONCURRENCY": "1",
            "WORKER_MAX_ACTIVE": "1",
            "WORKER_POLL_SECONDS": "0.05",
            "WORKER_HEARTBEAT_SECONDS": "0.5",
            "WORKER_RPC_TIMEOUT_SECONDS": "2",
            "WORKER_LEASE_SECONDS": "5",
        }
        child = subprocess.Popen(
            [sys.executable, "tests/durable_worker_process.py"],
            cwd=backend,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        self.addCleanup(self.stop, child)
        return child

    @staticmethod
    def stop(child):
        if child.poll() is None:
            child.kill()
        child.communicate(timeout=5)

    async def wait_for(self, query, expected, child):
        for _ in range(150):
            if await asyncio.to_thread(self.sql.run, query) == expected:
                return
            if child.poll() is not None:
                self.fail(child.communicate()[1].decode())
            await asyncio.sleep(0.05)
        self.fail("Worker did not reach expected durable state")

    async def test_queued_admission_survives_no_api_process(self):
        job = self.admit()["job_id"]
        child = self.launch()
        await self.wait_for(
            f"SELECT status FROM public.searches WHERE id='{job}'", "completed", child
        )
        self.assertEqual(self.sql.run("SELECT count(*) FROM public.worker_probe"), "1")
        self.assertEqual(
            self.sql.run("SELECT count(*) FROM public.usage_reservations"), "1"
        )

    async def test_kill_during_paid_graph_restart_interrupts_without_replay(self):
        job = self.admit()["job_id"]
        child = self.launch("provider")
        await self.wait_for(
            "SELECT count(*) FROM public.worker_probe WHERE event='provider'",
            "1",
            child,
        )
        self.stop(child)
        self.expire(job)
        restarted = self.launch()
        await self.wait_for(
            f"SELECT status FROM public.searches WHERE id='{job}'",
            "interrupted",
            restarted,
        )
        await asyncio.sleep(0.15)
        self.assertEqual(self.sql.run("SELECT count(*) FROM public.worker_probe"), "1")
        self.assertEqual(
            self.sql.run("SELECT count(*) FROM public.usage_reservations"), "1"
        )
        self.assertEqual(
            self.sql.run("SELECT count(*) FROM public.search_results"), "0"
        )

    async def test_kill_after_checkpoint_recovers_publication_only(self):
        job = self.admit()["job_id"]
        child = self.launch("publish")
        await self.wait_for(
            "SELECT count(*) FROM public.worker_probe WHERE event='checkpoint'",
            "1",
            child,
        )
        self.stop(child)
        self.expire(job)
        restarted = self.launch()
        await self.wait_for(
            f"SELECT status FROM public.searches WHERE id='{job}'",
            "completed",
            restarted,
        )
        self.assertEqual(
            self.sql.run(
                "SELECT count(*) FROM public.worker_probe WHERE event='provider'"
            ),
            "1",
        )
        self.assertEqual(self.sql.run("SELECT count(*) FROM public.patents"), "1")
        self.assertEqual(self.sql.run("SELECT evidence->'observations'->0->>'text' FROM public.patents"), "Evidence")
        self.assertEqual(
            self.sql.run("SELECT count(*) FROM public.usage_reservations"), "1"
        )

    async def test_two_processes_respect_global_capacity(self):
        import uuid

        first = self.admit()["job_id"]
        second = self.admit(key=str(uuid.uuid4()))["job_id"]
        worker1 = self.launch("provider")
        await self.wait_for(
            "SELECT count(*) FROM public.worker_probe WHERE event='provider'",
            "1",
            worker1,
        )
        worker2 = self.launch()
        await asyncio.sleep(0.8)
        self.assertEqual(
            self.sql.run(
                "SELECT count(*) FROM public.worker_probe WHERE event='provider'"
            ),
            "1",
        )
        self.assertEqual(
            self.sql.run(f"SELECT status FROM public.searches WHERE id='{second}'"),
            "queued",
        )
        self.stop(worker1)
        self.expire(first)
        await self.wait_for(
            f"SELECT status FROM public.searches WHERE id='{second}'",
            "completed",
            worker2,
        )
        self.assertEqual(
            self.sql.run(f"SELECT status FROM public.searches WHERE id='{first}'"),
            "interrupted",
        )
        self.assertEqual(
            self.sql.run(
                "SELECT count(*) FROM public.worker_probe WHERE event='provider'"
            ),
            "2",
        )
        self.assertEqual(
            self.sql.run("SELECT count(*) FROM public.usage_reservations"), "2"
        )

    async def test_saved_execution_options_and_all_real_graph_nodes(self):
        from test_milestone1_sql import SQLDatabase

        job = self.admit()["job_id"]
        claimed = self.rpc("claim_analysis", p_lease_seconds=60, p_max_active=1)
        with patch.object(settings, "mock_mode", False), patch(
            "app.services.llm.create_chat_completion", new=AsyncMock()
        ) as model, patch(
            "app.agents.nodes.fetcher.fetch_lens_patents", new=AsyncMock()
        ) as lens, patch(
            "app.agents.nodes.fetcher.fetch_serpapi_patents", new=AsyncMock()
        ) as serp:
            await run_claim(SQLDatabase(self.sql), claimed)
        self.assertEqual(
            self.sql.run(f"SELECT status FROM public.searches WHERE id='{job}'"),
            "completed",
        )
        self.assertEqual(self.sql.run("SELECT count(*) FROM public.patents"), "10")
        model.assert_not_awaited()
        lens.assert_not_awaited()
        serp.assert_not_awaited()


class DurableWorkerMockTest(unittest.IsolatedAsyncioTestCase):
    async def test_checkpoint_lost_response_never_marks_failed_or_repeats_graph(self):
        calls = []

        async def execute(name, params):
            calls.append(name)
            if name == "checkpoint_analysis":
                raise RuntimeError("committed but response lost")
            return SimpleNamespace(data=True)

        db = SimpleNamespace(
            rpc=lambda name, params: SimpleNamespace(
                execute=lambda: execute(name, params)
            )
        )
        graph = AsyncMock(return_value=state())
        with patch(
            "app.worker.build_graph", return_value=SimpleNamespace(ainvoke=graph)
        ):
            await run_claim(db, claim())
        graph.assert_awaited_once()
        self.assertNotIn("fail_analysis", calls)
        self.assertNotIn("publish_analysis", calls)

    async def test_stale_or_unavailable_lease_calls_no_provider(self):
        for response in (False, RuntimeError("store down")):
            db = SimpleNamespace(
                rpc=lambda *_: SimpleNamespace(
                    execute=AsyncMock(
                        return_value=SimpleNamespace(data=response),
                        side_effect=(
                            response if isinstance(response, Exception) else None
                        ),
                    )
                )
            )
            provider = AsyncMock()
            ctx = execution.set((Lease(db, claim()), claim()["execution_inputs"]))
            try:
                with self.assertRaises(LostLease):
                    await before_paid_call()
                    await provider()
            finally:
                execution.reset(ctx)
            provider.assert_not_awaited()
            with patch("app.worker.build_graph") as graph:
                await run_claim(db, claim())
                graph.assert_not_called()

    async def test_heartbeat_failure_cancels_inflight_graph(self):
        entered = asyncio.Event()
        cancelled = asyncio.Event()
        beats = 0

        async def execute(*_):
            nonlocal beats
            beats += 1
            return SimpleNamespace(data=beats == 1)

        async def graph(_):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        db = SimpleNamespace(rpc=lambda *_: SimpleNamespace(execute=execute))
        with patch.object(settings, "worker_heartbeat_seconds", 0.01), patch(
            "app.worker.build_graph", return_value=SimpleNamespace(ainvoke=graph)
        ):
            await asyncio.wait_for(run_claim(db, claim()), 1)
        self.assertTrue(entered.is_set())
        self.assertTrue(cancelled.is_set())
