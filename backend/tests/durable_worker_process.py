"""Production loop, real SQL, synthetic paid graph; used only by process tests."""

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import patch
from app.worker import serve
from app.services.execution import before_paid_call
from test_milestone1_sql import SQLDatabase, SQLHarness
from test_saved_results import state


async def main():
    sql = SQLHarness(os.environ["MILESTONE1_TEST_DSN"])
    db = SQLDatabase(sql)
    mode = os.environ.get("FIXTURE_STOP_AT", "")
    original_rpc = db.rpc

    def rpc(name, params):
        if name == "publish_analysis" and mode == "publish":

            async def blocked():
                sql.run("INSERT INTO public.worker_probe(event) VALUES ('checkpoint')")
                await asyncio.Event().wait()

            return SimpleNamespace(execute=blocked)
        return original_rpc(name, params)

    db.rpc = rpc

    async def graph(initial):
        await before_paid_call()
        sql.run("INSERT INTO public.worker_probe(event) VALUES ('provider')")
        if mode == "provider":
            await asyncio.Event().wait()
        final = state()
        final["search_id"] = initial["search_id"]
        return final

    async def get_db():
        return db

    with patch("app.worker.get_supabase", get_db), patch(
        "app.worker.build_graph", return_value=SimpleNamespace(ainvoke=graph)
    ):
        await serve()


asyncio.run(main())
