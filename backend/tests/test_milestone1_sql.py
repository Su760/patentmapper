"""Real PostgreSQL transactions/RLS, with HTTP routes and external providers mocked.

Run only against a dedicated local database named patentmapper_m1_test:
MILESTONE1_TEST_DSN='postgresql://.../patentmapper_m1_test' python -m unittest discover -s tests -p test_milestone1_sql.py -v
The fixture resets public/auth schemas in that disposable database.
"""
import asyncio
import uuid
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from urllib.parse import urlparse, parse_qs
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI

from app.api.routes import router
from app.db import get_supabase
from app.core.config import settings
from test_private_analyses import OWNER, OTHER, GUEST, JOB, LEGACY, GUEST_JOB, IDEA, IDEATION


ROOT = Path(__file__).resolve().parents[2]


def literal(value):
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


class SQLHarness:
    def __init__(self, dsn):
        self.dsn = dsn

    def run(self, sql):
        result = subprocess.run(["psql", "-X", "-qAt", "-v", "ON_ERROR_STOP=1", self.dsn, "-c", sql], capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise RuntimeError(result.stderr.strip())
        return result.stdout.strip()

    def apply(self, path):
        return self.run(path.read_text())


class SQLQuery:
    def __init__(self, db, table):
        if table not in ("searches", "search_results", "patents"):
            raise ValueError(table)
        self.db, self.table = db, table
        self.filters, self.operation, self.payload, self.maximum = {}, "select", None, None

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, key, value):
        if key not in ("id", "user_id", "search_id"):
            raise ValueError(key)
        self.filters[key] = value
        return self

    def limit(self, count):
        self.maximum = int(count)
        return self

    def update(self, payload):
        self.operation, self.payload = "update", payload
        return self

    def insert(self, payload):
        self.operation, self.payload = "insert", payload
        return self

    async def execute(self):
        where = " AND ".join(f"{k} = {literal(v)}" for k, v in self.filters.items()) or "true"
        if self.operation == "select":
            limit = f" LIMIT {self.maximum}" if self.maximum is not None else ""
            query = f"SELECT coalesce(json_agg(t), '[]'::json) FROM (SELECT * FROM public.{self.table} WHERE {where}{limit}) t"
        elif self.operation == "insert":
            if self.table != "searches":
                raise AssertionError("Unexpected insert: background provider work must be mocked")
            columns = "id,user_id,invention_idea,status,current_step"
            values = ",".join(literal(self.payload[c]) for c in columns.split(","))
            query = f"WITH t AS (INSERT INTO public.searches ({columns}) VALUES ({values}) RETURNING *) SELECT json_agg(t) FROM t"
        else:
            assert self.table == "search_results" and set(self.payload) == {"claims_analysis"}
            data = literal(json.dumps(self.payload["claims_analysis"]))
            query = f"WITH t AS (UPDATE public.search_results SET claims_analysis={data}::jsonb WHERE {where} RETURNING *) SELECT coalesce(json_agg(t), '[]'::json) FROM t"
        output = await asyncio.to_thread(self.db.sql.run, f"SET ROLE service_role; {query}")
        return SimpleNamespace(data=json.loads(output))


class SQLDatabase:
    """Minimal test adapter using real service-role SQL rather than a fake quota lock."""
    def __init__(self, sql):
        self.sql = sql
        async def get_user(token):
            user_id = {"owner": OWNER, "other": OTHER, "guest": GUEST}.get(token)
            if not user_id:
                raise ValueError("invalid test token")
            return SimpleNamespace(user=SimpleNamespace(id=user_id, is_anonymous=token == "guest"))
        self.auth = SimpleNamespace(get_user=AsyncMock(side_effect=get_user))

    def table(self, name):
        return SQLQuery(self, name)

    def rpc(self, name, params):
        assert name in ("reserve_paid_operation", "admit_analysis", "claim_analysis", "read_analysis_status", "heartbeat_analysis", "stage_analysis", "checkpoint_analysis", "fail_analysis", "publish_analysis")
        async def execute():
            args = ",".join(f"{k} => {literal(json.dumps(v) if isinstance(v, (dict,list)) else v)}" for k, v in params.items())
            result = await asyncio.to_thread(self.sql.run, f"SET ROLE service_role; SELECT public.{name}({args})")
            data = result if name == "reserve_paid_operation" else (result == "t") if result in ("t","f") else json.loads(result) if result else None
            return SimpleNamespace(data=data)
        return SimpleNamespace(execute=execute)


class Milestone1SQLTest(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        dsn = os.environ.get("MILESTONE1_TEST_DSN")
        if not dsn:
            raise unittest.SkipTest("Set MILESTONE1_TEST_DSN to a dedicated local patentmapper_m1_test database")
        parsed = urlparse(dsn)
        host = parsed.hostname or parse_qs(parsed.query).get("host", [""])[0]
        if parsed.path != "/patentmapper_m1_test" or not (host in ("localhost", "127.0.0.1", "::1") or host.startswith("/")):
            raise RuntimeError("Refusing schema reset outside a local database named patentmapper_m1_test")
        if not shutil.which("psql"):
            raise RuntimeError("psql is required for SQL integration tests")
        cls.sql = SQLHarness(dsn)
        cls.sql.apply(ROOT / "supabase/tests/bootstrap.sql")
        for path in sorted((ROOT / "supabase/migrations").glob("*.sql")):
            cls.sql.apply(path)

    async def asyncSetUp(self):
        self.sql.run("TRUNCATE public.usage_reservations, public.patents, public.search_results, public.searches, public.subscriptions, auth.users CASCADE")
        self.sql.run(f"""
            INSERT INTO auth.users(id,is_anonymous) VALUES ('{OWNER}',false),('{OTHER}',false),('{GUEST}',true);
            INSERT INTO public.searches(id,user_id,invention_idea,status) VALUES ('{JOB}','{OWNER}','{IDEA}','completed'),('{GUEST_JOB}','{GUEST}','{IDEA}','completed');
            -- Simulate an ownerless historical row predating the new-row constraint.
            ALTER TABLE public.searches DROP CONSTRAINT searches_owner_required;
            INSERT INTO public.searches(id,user_id,invention_idea,status) VALUES ('{LEGACY}',NULL,'{IDEA}','completed');
            ALTER TABLE public.searches ADD CONSTRAINT searches_owner_required CHECK (user_id IS NOT NULL) NOT VALID;
            INSERT INTO public.search_results(search_id,claims_analysis) SELECT id,'[]'::jsonb FROM public.searches;
            INSERT INTO public.patents(search_id,patent_id,title,abstract) SELECT id,'fixture','Fixture','Fixture abstract' FROM public.searches;
        """)
        app = FastAPI()
        app.include_router(router, prefix="/api")
        db = SQLDatabase(self.sql)
        app.dependency_overrides[get_supabase] = lambda: db
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture")
        self.addAsyncCleanup(self.client.aclose)
        self.graph = self.enterContext(patch("app.worker.run_claim", new=AsyncMock()))
        self.model = self.enterContext(patch("app.api.routes.create_chat_completion", new=AsyncMock(return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"claims":[],"invention_name":"Fixture"}'))]))))
        self.groq = self.enterContext(patch("app.api.routes.AsyncGroq"))
        self.lens = self.enterContext(patch("app.agents.nodes.fetcher.fetch_lens_patents", new=AsyncMock()))
        self.serp = self.enterContext(patch("app.agents.nodes.fetcher.fetch_serpapi_patents", new=AsyncMock()))

    async def request(self, method, path, token="owner", body=None):
        if path == "/api/jobs" and isinstance(body, dict):
            body = {"submission_key": str(uuid.uuid4()), **body}
        return await self.client.request(method, path, headers={"Authorization": f"Bearer {token}"}, json=body)

    def browser_sql(self, role, user_id, query):
        return self.sql.run(f"SET ROLE {role}; SET request.jwt.claim.sub = {literal(user_id)}; {query}")

    async def test_committed_admission_response_loss_http_retry_is_idempotent(self):
        db=self.client._transport.app.dependency_overrides[get_supabase]()
        original=db.rpc
        lost=True
        def rpc(name,params):
            real=original(name,params)
            async def execute():
                nonlocal lost
                result=await real.execute()
                if name=='admit_analysis' and lost:
                    lost=False
                    raise RuntimeError('committed admission response lost')
                return result
            return SimpleNamespace(execute=execute)
        db.rpc=rpc
        self.client._transport.app.dependency_overrides[get_supabase]=lambda:db
        body={"invention_idea":IDEA,"submission_key":str(uuid.uuid4())}
        first=await self.request('POST','/api/jobs',body=body)
        self.assertEqual(first.status_code,503)
        self.assertIn('same inputs and submission key',first.text)
        second=await self.request('POST','/api/jobs',body=body)
        self.assertEqual(second.status_code,202)
        self.assertEqual(self.sql.run('SELECT count(*) FROM public.analysis_queue'),'1')
        self.assertEqual(self.sql.run('SELECT count(*) FROM public.usage_reservations'),'1')
        self.graph.assert_not_awaited();self.lens.assert_not_awaited();self.serp.assert_not_awaited()

    async def test_snapshot_uses_reservations_custom_window_and_failed_attempts(self):
        self.sql.run(f"INSERT INTO public.usage_reservations(user_id,operation,created_at) VALUES ('{OWNER}','job',now()),('{OWNER}','claims',now()),('{OWNER}','ideation',now()-interval '8 days')")
        data = json.loads(self.sql.run(f"SET ROLE service_role; SELECT public.paid_usage_snapshot('{OWNER}',604800)"))
        self.assertEqual(data["used"], {"job":1,"claims":1,"ideation":0})
        self.assertEqual(data["window_seconds"],604800)
        # No new search row exists for the reserved job: attempted work still counts.
        with patch.object(settings, "free_job_limit", 1), patch.object(settings, "quota_window_days", 7):
            self.assertEqual((await self.request("POST", "/api/jobs", body={"invention_idea": IDEA})).status_code,402)
        for role in ("anon", "authenticated"):
            with self.assertRaisesRegex(RuntimeError,"permission denied"):
                self.sql.run(f"SET ROLE {role}; SELECT public.paid_usage_snapshot('{OWNER}',604800)")

    async def test_browser_rls_owners_other_users_anonymous_and_ownerless(self):
        for table, id_column in (("searches", "id"), ("search_results", "search_id"), ("patents", "search_id")):
            for user, job in ((OWNER, JOB), (GUEST, GUEST_JOB)):
                with self.subTest(table=table, user=user):
                    self.assertEqual(self.browser_sql("authenticated", user, f"SELECT count(*) FROM public.{table} WHERE {id_column}='{job}'"), "1")
            for role, user in (("authenticated", OTHER), ("anon", "")):
                self.assertEqual(self.browser_sql(role, user, f"SELECT count(*) FROM public.{table}"), "0")
            self.assertEqual(self.browser_sql("authenticated", OWNER, f"SELECT count(*) FROM public.{table} WHERE {id_column}='{LEGACY}'"), "0")
            for user in (OWNER, OTHER):
                for command in (f"UPDATE public.{table} SET {id_column}={id_column} WHERE {id_column}='{JOB}'", f"DELETE FROM public.{table} WHERE {id_column}='{JOB}'", f"INSERT INTO public.{table} ({id_column}) VALUES ('{JOB}')"):
                    with self.assertRaisesRegex(RuntimeError, "permission denied"):
                        self.browser_sql("authenticated", user, command)
        for table in ("usage_reservations", "subscriptions"):
            with self.assertRaisesRegex(RuntimeError, "permission denied"):
                self.browser_sql("authenticated", OWNER, f"UPDATE public.{table} SET user_id='{OTHER}'")

    async def test_http_cross_user_cannot_read_or_modify_and_owners_succeed(self):
        for method, suffix, body in (("GET", "", None), ("GET", "/analyze-claims", None), ("POST", "/analyze-claims", None), ("POST", "/ideate", IDEATION)):
            self.assertEqual((await self.request(method, f"/api/jobs/{JOB}{suffix}", "other", body)).status_code, 404)
            self.assertEqual((await self.request(method, f"/api/jobs/{LEGACY}{suffix}", "owner", body)).status_code, 404)
        self.model.assert_not_awaited(); self.graph.assert_not_awaited()
        self.groq.assert_not_called(); self.lens.assert_not_awaited(); self.serp.assert_not_awaited()
        self.assertEqual(self.sql.run("SELECT count(*) FROM public.usage_reservations"), "0")
        self.assertEqual((await self.request("GET", f"/api/jobs/{JOB}")).status_code, 200)
        self.assertEqual((await self.request("POST", f"/api/jobs/{JOB}/analyze-claims")).status_code, 200)
        self.assertEqual(self.sql.run(f"SELECT user_id FROM public.searches WHERE id='{JOB}'"), OWNER)

    async def test_real_concurrent_http_last_unit_for_each_paid_operation(self):
        for operation, path, body, limit in (("job", "/api/jobs", {"invention_idea": IDEA}, settings.free_job_limit), ("claims", f"/api/jobs/{JOB}/analyze-claims", None, settings.free_claims_limit), ("ideation", f"/api/jobs/{JOB}/ideate", IDEATION, settings.free_ideation_limit)):
            self.sql.run(f"TRUNCATE public.usage_reservations; INSERT INTO public.usage_reservations(user_id,operation) SELECT '{OWNER}','{operation}' FROM generate_series(1,{limit - 1})")
            self.model.reset_mock(); self.graph.reset_mock()
            responses = await asyncio.gather(*(self.request("POST", path, body=body) for _ in range(8)))
            with self.subTest(operation=operation):
                self.assertEqual(sum(r.status_code in (200, 202) for r in responses), 1)
                self.assertEqual(sum(r.status_code == 402 for r in responses), 7)
                self.assertEqual(self.model.await_count + self.graph.await_count, 0 if operation == "job" else 1)
                self.assertEqual(self.sql.run("SELECT count(*) FROM public.usage_reservations"), str(limit))

    async def test_quota_store_failure_launches_no_paid_work(self):
        self.sql.run("ALTER TABLE public.usage_reservations RENAME TO unavailable_usage_reservations")
        try:
            for path, body in (("/api/jobs", {"invention_idea": IDEA}), (f"/api/jobs/{JOB}/analyze-claims", None), (f"/api/jobs/{JOB}/ideate", IDEATION)):
                self.assertEqual((await self.request("POST", path, body=body)).status_code, 503)
            self.model.assert_not_awaited(); self.graph.assert_not_awaited()
            self.groq.assert_not_called(); self.lens.assert_not_awaited(); self.serp.assert_not_awaited()
        finally:
            self.sql.run("ALTER TABLE public.unavailable_usage_reservations RENAME TO usage_reservations")

    async def test_rpc_is_service_only_and_global_cap_survives_account_changes(self):
        for role in ("anon", "authenticated"):
            with self.assertRaisesRegex(RuntimeError, "permission denied for function"):
                self.browser_sql(role, OWNER, f"SELECT public.reserve_paid_operation('{OWNER}','claims',3,100,1,2592000)")
        def reserve(user, operation):
            return self.sql.run(f"SET ROLE service_role; SELECT public.reserve_paid_operation('{user}','{operation}',3,100,1,2592000)")
        with ThreadPoolExecutor(max_workers=2) as pool:
            answers = list(pool.map(lambda args: reserve(*args), [(OWNER, "claims"), (OTHER, "ideation")]))
        self.assertCountEqual(answers, ["allowed", "global_limit"])
        admitted = self.sql.run("SELECT user_id FROM public.usage_reservations")
        self.sql.run(f"DELETE FROM auth.users WHERE id='{admitted}'")
        self.assertEqual(reserve(GUEST, "claims"), "global_limit")

    async def test_legacy_backfill_idempotent_and_new_ownerless_searches_denied(self):
        self.sql.apply(ROOT / "supabase/migrations/202610020002_bounded_usage.sql")
        self.sql.apply(ROOT / "supabase/migrations/202610020002_bounded_usage.sql")
        self.sql.apply(ROOT / "supabase/migrations/202610020003_usage_snapshot.sql")
        self.assertEqual(self.sql.run("SELECT count(*) FROM public.usage_reservations WHERE operation='job'"), "3")
        self.assertEqual(self.sql.run(f"SELECT count(*) FROM public.searches WHERE id='{LEGACY}' AND user_id IS NULL"), "1")
        with self.assertRaisesRegex(RuntimeError, "searches_owner_required"):
            self.sql.run("INSERT INTO public.searches(invention_idea) VALUES ('forbidden ownerless job')")

    async def test_upgrade_replaces_permissive_policies_without_losing_rows(self):
        self.sql.run("""
            CREATE POLICY old_public_read ON public.searches FOR SELECT TO anon, authenticated USING (true);
            CREATE POLICY old_public_results ON public.search_results FOR ALL TO authenticated USING (true) WITH CHECK (true);
            GRANT ALL ON public.search_results TO authenticated;
        """)
        self.assertEqual(self.browser_sql("authenticated", OTHER, "SELECT count(*) FROM public.searches"), "3")
        self.sql.apply(ROOT / "supabase/migrations/202610020001_private_analyses.sql")
        self.assertEqual(self.browser_sql("authenticated", OTHER, "SELECT count(*) FROM public.searches"), "0")
        self.assertEqual(self.browser_sql("anon", "", "SELECT count(*) FROM public.searches"), "0")
        with self.assertRaisesRegex(RuntimeError, "permission denied"):
            self.browser_sql("authenticated", OTHER, "UPDATE public.search_results SET claims_analysis='[]'")
        self.assertEqual(self.sql.run("SELECT count(*) FROM public.searches"), "3")
        self.assertEqual(self.sql.run("SELECT count(*) FROM public.search_results"), "3")

    async def test_pro_expiry_and_verified_anonymous_users_still_have_finite_limits(self):
        self.sql.run(f"INSERT INTO public.subscriptions(user_id,plan,status) VALUES ('{OWNER}','pro','active'),('{GUEST}','pro','active')")
        def reserve(user):
            return self.sql.run(f"SET ROLE service_role; SELECT public.reserve_paid_operation('{user}','claims',1,2,100,2592000)")
        self.assertEqual(reserve(OWNER), "allowed")
        self.assertEqual(reserve(OWNER), "allowed")
        self.assertEqual(reserve(OWNER), "user_limit")
        self.assertEqual(reserve(GUEST), "allowed")
        self.assertEqual(reserve(GUEST), "user_limit")
        self.sql.run(f"UPDATE public.subscriptions SET current_period_end=now()-interval '1 day' WHERE user_id='{OWNER}'; DELETE FROM public.usage_reservations WHERE user_id='{OWNER}'")
        self.assertEqual(reserve(OWNER), "allowed")
        self.assertEqual(reserve(OWNER), "user_limit")

    async def test_subscription_store_failure_is_also_fail_closed(self):
        self.sql.run("ALTER TABLE public.subscriptions RENAME TO unavailable_subscriptions")
        try:
            self.assertEqual((await self.request("POST", "/api/jobs", body={"invention_idea": IDEA})).status_code, 503)
            self.model.assert_not_awaited(); self.graph.assert_not_awaited()
            self.groq.assert_not_called(); self.lens.assert_not_awaited(); self.serp.assert_not_awaited()
        finally:
            self.sql.run("ALTER TABLE public.unavailable_subscriptions RENAME TO subscriptions")


if __name__ == "__main__":
    unittest.main()
