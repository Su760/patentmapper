"""HTTP security regressions. External services are mocked; no real keys required."""
import asyncio
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI

from app.api.routes import router
from app.db import get_supabase
from app.services.patent_api import fetch_lens_patents
from security_fixtures import MemoryDB, MemoryQuery


OWNER = "00000000-0000-0000-0000-000000000001"
OTHER = "00000000-0000-0000-0000-000000000002"
GUEST = "00000000-0000-0000-0000-000000000003"
JOB = "10000000-0000-0000-0000-000000000001"
LEGACY = "10000000-0000-0000-0000-000000000002"
GUEST_JOB = "10000000-0000-0000-0000-000000000003"
IDEATION = {"white_space_title": "A synthetic gap", "white_space_description": "A fixture description for testing."}
IDEA = "An automated irrigation controller with humidity sensors."


class Query(MemoryQuery):
    def limit(self, *_args):
        return self


class SecurityDB(MemoryDB):
    def __init__(self):
        super().__init__()
        self.rows["subscriptions"] = []
        self.rows["searches"] = [
            {"id": JOB, "user_id": OWNER, "status": "completed", "invention_idea": IDEA},
            {"id": LEGACY, "user_id": None, "status": "completed", "invention_idea": IDEA},
            {"id": GUEST_JOB, "user_id": GUEST, "status": "completed", "invention_idea": IDEA},
        ]
        self.rows["search_results"] = [{"search_id": JOB, "claims_analysis": [{"patent_id": "fixture"}]}]
        self.rows["patents"] = [{"search_id": JOB, "patent_id": "fixture", "title": "Fixture", "abstract": "Fixture abstract"}]
        self.auth = SimpleNamespace(get_user=AsyncMock(side_effect=self.get_user))
        self.reservations = []
        self.quota_failure = False
        self.quota_response = None
        self.lock = asyncio.Lock()
        self.reads = []

    async def get_user(self, token):
        if token in ("invalid", "expired"):
            raise RuntimeError("Rejected access token")
        user_id = {"owner": OWNER, "other": OTHER, "guest": GUEST}.get(token)
        return SimpleNamespace(user=SimpleNamespace(id=user_id, is_anonymous=token == "guest") if user_id else None)

    def table(self, name):
        self.reads.append(name)
        return Query(self, name)

    def rpc(self, name, params):
        assert name == "reserve_paid_operation"

        async def execute():
            if self.quota_failure:
                raise RuntimeError("synthetic quota store outage")
            if self.quota_response is not None:
                return SimpleNamespace(data=self.quota_response)
            async with self.lock:
                # Deliberately yield inside the critical section: unprotected checks race.
                await asyncio.sleep(0)
                if "subscriptions" in self.fail_tables:
                    raise RuntimeError("synthetic subscription outage")
                user, operation = params["p_user_id"], params["p_operation"]
                pro = user != GUEST and any(r["user_id"] == user and r["plan"] == "pro" and r["status"] == "active" for r in self.rows["subscriptions"])
                limit = params["p_pro_limit"] if pro else params["p_free_limit"]
                if sum(r == (user, operation) for r in self.reservations) >= limit:
                    return SimpleNamespace(data="user_limit")
                if len(self.reservations) >= params["p_global_limit"]:
                    return SimpleNamespace(data="global_limit")
                self.reservations.append((user, operation))
                return SimpleNamespace(data="allowed")

        return SimpleNamespace(execute=execute)


class PrivateAnalysesTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = SecurityDB()
        app = FastAPI()
        app.include_router(router, prefix="/api")
        app.dependency_overrides[get_supabase] = lambda: self.db
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture")
        self.addAsyncCleanup(self.client.aclose)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.graph = self.stack.enter_context(patch("app.api.routes._run_graph", new=AsyncMock()))
        self.model = self.stack.enter_context(patch("app.api.routes.create_chat_completion", new=AsyncMock(return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"claims": [], "invention_name": "Fixture"})))]))))
        self.groq = self.stack.enter_context(patch("app.api.routes.AsyncGroq"))
        self.lens = self.stack.enter_context(patch("app.agents.nodes.fetcher.fetch_lens_patents", new=AsyncMock()))
        self.serp = self.stack.enter_context(patch("app.agents.nodes.fetcher.fetch_serpapi_patents", new=AsyncMock()))

    async def request(self, method, path, token="owner", body=None):
        headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
        return await self.client.request(method, path, headers=headers, json=body)

    def assert_no_paid_work(self):
        self.graph.assert_not_awaited()
        self.model.assert_not_awaited()
        self.groq.assert_not_called()
        self.lens.assert_not_awaited()
        self.serp.assert_not_awaited()

    async def test_authentication_precedes_malformed_json(self):
        for path in ("/api/jobs", f"/api/jobs/{JOB}/ideate"):
            for token in (None, "invalid", "expired"):
                headers = {"Content-Type": "application/json"}
                if token:
                    headers["Authorization"] = f"Bearer {token}"
                r = await self.client.post(path, headers=headers, content="{")
                self.assertEqual(r.status_code, 401)
            r = await self.client.post(path, headers={"Authorization": "Bearer owner", "Content-Type": "application/json"}, content="{")
            self.assertEqual(r.status_code, 422)
        self.assertEqual(self.db.reservations, [])
        self.assert_no_paid_work()

    async def test_foreign_job_is_hidden_even_with_invalid_ideation_body(self):
        for body in ("{", "{}"):
            r = await self.client.post(f"/api/jobs/{JOB}/ideate", headers={"Authorization":"Bearer other", "Content-Type":"application/json"}, content=body)
            self.assertEqual(r.status_code, 404)
        self.assertEqual(self.db.reservations, [])
        self.assert_no_paid_work()

    async def test_owner_access_all_endpoints(self):
        for method, path, body, code in [
            ("GET", f"/api/jobs/{JOB}", None, 200),
            ("GET", f"/api/jobs/{JOB}/analyze-claims", None, 200),
            ("POST", f"/api/jobs/{JOB}/analyze-claims", None, 200),
            ("POST", f"/api/jobs/{JOB}/ideate", IDEATION, 200),
            ("POST", "/api/jobs", {"invention_idea": IDEA, "jurisdiction": "us"}, 202),
        ]:
            with self.subTest(path=path, method=method):
                self.assertEqual((await self.request(method, path, body=body)).status_code, code)
        self.assertEqual(self.db.rows["searches"][-1]["user_id"], OWNER)
        self.assertEqual(self.db.reservations, [(OWNER, "claims"), (OWNER, "ideation"), (OWNER, "job")])

    async def test_missing_invalid_expired_and_malformed_credentials_never_become_anonymous(self):
        for token in (None, "invalid", "expired", "unknown", ""):
            for method, path, body in [
                ("POST", "/api/jobs", {"invention_idea": IDEA}),
                ("GET", f"/api/jobs/{JOB}", None),
                ("GET", f"/api/jobs/{JOB}/analyze-claims", None),
                ("POST", f"/api/jobs/{JOB}/analyze-claims", None),
                ("POST", f"/api/jobs/{JOB}/ideate", IDEATION),
            ]:
                with self.subTest(token=token, path=path, method=method):
                    self.assertEqual((await self.request(method, path, token, body)).status_code, 401)
        for header in ("Basic owner", "Bearer owner extra", "Bearer", "Bearer \t"):
            r = await self.client.get(f"/api/jobs/{JOB}", headers={"Authorization": header})
            self.assertEqual(r.status_code, 401)
        self.assertEqual(self.db.reads, [])
        self.assertEqual(self.db.reservations, [])
        self.assert_no_paid_work()

    async def test_cross_user_missing_and_ownerless_jobs_are_404_before_any_paid_work(self):
        snapshot = copy.deepcopy(self.db.rows)
        for job, token in ((JOB, "other"), (LEGACY, "owner"), ("10000000-0000-0000-0000-999999999999", "owner")):
            for method, suffix, body in (("GET", "", None), ("GET", "/analyze-claims", None), ("POST", "/analyze-claims", None), ("POST", "/ideate", IDEATION)):
                with self.subTest(job=job, token=token, method=method, suffix=suffix):
                    response = await self.request(method, f"/api/jobs/{job}{suffix}", token, body)
                    self.assertEqual(response.status_code, 404)
        self.assertEqual(self.db.rows, snapshot)
        self.assertTrue(all(table == "searches" for table in self.db.reads))
        self.assert_no_paid_work()

    async def test_verified_anonymous_session_owns_jobs_and_signed_out_uuid_or_demo_is_not_authorization(self):
        self.assertEqual((await self.request("GET", f"/api/jobs/{GUEST_JOB}", "guest")).status_code, 200)
        self.assertEqual((await self.request("GET", f"/api/jobs/{GUEST_JOB}", "owner")).status_code, 404)
        for job in (GUEST_JOB, "demo"):
            self.assertEqual((await self.request("GET", f"/api/jobs/{job}", None)).status_code, 401)
        for _ in range(3):
            self.assertEqual((await self.request("POST", "/api/jobs", "guest", {"invention_idea": IDEA})).status_code, 202)
        self.assertEqual((await self.request("POST", "/api/jobs", "guest", {"invention_idea": IDEA})).status_code, 402)
        self.assertTrue(all(r["user_id"] == GUEST for r in self.db.rows["searches"][3:]))

    async def test_quota_and_subscription_store_failures_launch_no_paid_work(self):
        for failure in ("quota", "subscriptions", "unexpected_response"):
            self.db.quota_failure = failure == "quota"
            self.db.fail_tables = {"subscriptions"} if failure == "subscriptions" else set()
            self.db.quota_response = {"allowed": True} if failure == "unexpected_response" else None
            for path, body in (("/api/jobs", {"invention_idea": IDEA}), (f"/api/jobs/{JOB}/analyze-claims", None), (f"/api/jobs/{JOB}/ideate", IDEATION)):
                with self.subTest(failure=failure, path=path):
                    self.assertEqual((await self.request("POST", path, body=body)).status_code, 503)
        self.assert_no_paid_work()
        self.assertEqual(self.db.reservations, [])

    async def test_concurrent_last_unit_for_every_paid_operation(self):
        for operation, path, body, limit in (("job", "/api/jobs", {"invention_idea": IDEA}, 3), ("claims", f"/api/jobs/{JOB}/analyze-claims", None, 3), ("ideation", f"/api/jobs/{JOB}/ideate", IDEATION, 6)):
            self.db.reservations = [(OWNER, operation)] * (limit - 1)
            self.graph.reset_mock(); self.model.reset_mock()
            responses = await asyncio.gather(*(self.request("POST", path, body=body) for _ in range(8)))
            with self.subTest(operation=operation):
                self.assertEqual(sum(r.status_code in (200, 202) for r in responses), 1)
                self.assertEqual(sum(r.status_code == 402 for r in responses), 7)
                self.assertEqual(self.graph.await_count + self.model.await_count, 1)

    async def test_pro_and_global_budget_are_finite(self):
        from app.core.config import settings
        self.db.rows["subscriptions"] = [{"user_id": OWNER, "plan": "pro", "status": "active"}]
        self.db.reservations = [(OWNER, "job")] * settings.pro_job_limit
        self.assertEqual((await self.request("POST", "/api/jobs", body={"invention_idea": IDEA})).status_code, 402)
        self.db.reservations = [(OTHER, "ideation")] * settings.global_operation_limit
        self.assertEqual((await self.request("POST", f"/api/jobs/{JOB}/ideate", body=IDEATION)).status_code, 429)
        self.assert_no_paid_work()

    async def test_invalid_inputs_denied_before_paid_work(self):
        for body in ({"invention_idea": " " * 30}, {"invention_idea": "short"}, {"invention_idea": "x" * 2001}, {"invention_idea": IDEA, "jurisdiction": "invalid"}, {"invention_idea": IDEA, "user_id": OTHER}):
            self.assertEqual((await self.request("POST", "/api/jobs", body=body)).status_code, 422)
        for body in (IDEATION | {"white_space_title": "x" * 201}, IDEATION | {"white_space_description": "x" * 4001}, IDEATION | {"white_space_title": "  "}):
            self.assertEqual((await self.request("POST", f"/api/jobs/{JOB}/ideate", body=body)).status_code, 422)
        self.assertEqual((await self.request("GET", "/api/jobs/not-a-uuid")).status_code, 422)
        self.assertEqual(self.db.reservations, [])
        self.assert_no_paid_work()

    async def test_lens_authorization_header_is_never_logged(self):
        token = "synthetic-lens-secret"
        client = SimpleNamespace(post=AsyncMock(return_value=httpx.Response(200, json={"data": []}, request=httpx.Request("POST", "https://fixture.invalid"))))
        with patch("app.services.patent_api.logger") as logger:
            await fetch_lens_patents("fixture", client, token)
        self.assertNotIn(token, str(logger.mock_calls))
        self.assertNotIn("Authorization", str(logger.mock_calls))

    async def test_missing_credentials_denied_even_when_database_client_cannot_initialize(self):
        db = AsyncMock(side_effect=RuntimeError("client setup unavailable"))
        async def unavailable_db():
            return await db()
        self.client._transport.app.dependency_overrides[get_supabase] = unavailable_db
        for method, path, body in (("POST", "/api/jobs", {"invention_idea": IDEA}), ("GET", f"/api/jobs/{JOB}", None)):
            self.assertEqual((await self.request(method, path, None, body)).status_code, 401)
        db.assert_not_awaited()
        self.assert_no_paid_work()

    async def test_invalid_or_expired_credentials_take_precedence_over_invalid_creation_body(self):
        for token in ("invalid", "expired"):
            self.assertEqual((await self.request("POST", "/api/jobs", token, {"invention_idea": "short"})).status_code, 401)
        self.assert_no_paid_work()

    async def test_failed_model_attempts_remain_consumed_and_cannot_reset_usage(self):
        self.model.side_effect = RuntimeError("synthetic provider outage")
        for path, body, operation, limit in ((f"/api/jobs/{JOB}/analyze-claims", None, "claims", 3), (f"/api/jobs/{JOB}/ideate", IDEATION, "ideation", 6)):
            self.db.reservations = [(OWNER, operation)] * (limit - 1)
            with self.assertLogs("app.api.routes", level="ERROR"):
                self.assertEqual((await self.request("POST", path, body=body)).status_code, 500)
            self.model.reset_mock(); self.groq.reset_mock()
            self.assertEqual((await self.request("POST", path, body=body)).status_code, 402)
            self.model.assert_not_awaited(); self.groq.assert_not_called()


class BrowserAPIContractTest(unittest.TestCase):
    def test_browser_credentials_demo_and_errors_without_network(self):
        frontend = Path(__file__).resolve().parents[2] / "frontend"
        if not shutil.which("node") or not (frontend / "node_modules/typescript").exists():
            if os.environ.get("REQUIRE_FRONTEND_TESTS") == "1":
                self.fail("Install frontend dependencies and Node before running required browser API tests")
            self.skipTest("Install frontend dependencies and Node to run browser API contract")
        result = subprocess.run(["node", "-e", r'''
const fs=require('node:fs'), vm=require('node:vm'), assert=require('node:assert/strict'), ts=require('typescript');
let token=null, authError=null, calls=[];
const supabase={createClient:()=>({auth:{getSession:async()=>({data:{session:token?{access_token:token}:null},error:authError})}})};
let response={ok:true,status:200,json:async()=>({job_id:'owned',status:'completed',claims:[]})};
function load(path, deps={}) {
  const module={exports:{}};
  const source=ts.transpileModule(fs.readFileSync(path,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
  vm.runInNewContext(source,{module,exports:module.exports,require:name=>{assert.ok(name in deps,name);return deps[name]},process:{env:{}},structuredClone,
    fetch:async(url,options)=>{calls.push({url,options});return response}});
  return module.exports;
}
const demo=load('src/lib/demo.ts');
const api=load('src/lib/api.ts',{'@/lib/supabase':supabase,'@/lib/demo':demo});
(async()=>{
  const privateCalls=[()=>api.createJob('An invention description for test','us'),()=>api.getJobStatus('owned'),()=>api.getClaimsAnalysis('owned'),()=>api.analyzeClaimsRequest('owned'),()=>api.ideateWhiteSpace('owned','Gap','Description')];
  for(const call of privateCalls) await assert.rejects(call,/Sign in/);
  assert.equal(calls.length,0);
  const first=JSON.stringify(await api.getJobStatus('demo'));
  assert.equal(JSON.stringify(await api.getJobStatus('demo')),first);
  assert.equal(JSON.stringify(await api.ideateWhiteSpace('demo','a','b')),JSON.stringify(await api.ideateWhiteSpace('demo','different','input')));
  const claims=await api.analyzeClaimsRequest('demo');claims.claims.length=0;
  assert.equal((await api.getClaimsAnalysis('demo')).claims.length,1);
  assert.equal(calls.length,0); // All demo behavior is local, deterministic, and public.
  token='verified-token';
  for(const call of privateCalls) await call();
  assert.equal(calls.length,5);
  assert.ok(calls.every(c=>c.options.headers.Authorization==='Bearer verified-token'));
  assert.equal(calls[1].options.cache,'no-store');assert.equal(calls[2].options.cache,'no-store');
  response={ok:false,status:401,json:async()=>({detail:'expired'})};
  for(const call of privateCalls) await assert.rejects(call,/expired/);
  response={ok:false,status:404,json:async()=>({detail:'missing'})};
  await assert.rejects(()=>api.getJobStatus('foreign'),/unavailable/);
  response={ok:false,status:503,json:async()=>({detail:'Usage store unavailable; no paid work started'})};
  await assert.rejects(()=>api.analyzeClaimsRequest('owned'),/no paid work/);
  const oldCount=calls.length;authError=new Error('session failed');
  await assert.rejects(()=>api.getJobStatus('owned'),/Sign in/);assert.equal(calls.length,oldCount);
  response={ok:false,status:403,json:async()=>({detail:'Sign in or create a permanent account before upgrading.'})};
  await assert.rejects(()=>api.createCheckoutSession('verified-anonymous-token'),/permanent account/);
  console.log('Browser API contract: credentials, denial, quota errors, deterministic demo and zero demo network calls verified.');
})().catch(e=>{console.error(e);process.exitCode=1});
'''], cwd=frontend, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
