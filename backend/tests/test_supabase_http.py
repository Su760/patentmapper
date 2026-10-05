"""Real local GoTrue/PostgREST/SDK integration; model/patent work is mocked.

MILESTONE1_SUPABASE_CONFIG points to `supabase status -o json` for a disposable
local stack with the migrations applied and anonymous sign-ins enabled.
Never use an application database: tests temporarily rename the quota table.
"""
import asyncio
import uuid
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import subprocess
import time
import unittest
from types import SimpleNamespace
from urllib.parse import urlparse
from uuid import uuid4
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI
from supabase import create_async_client

from app.api.routes import router
from app.worker import run_claim as run_saved_graph
from app.api.stripe_routes import router as billing_router
from app.core.config import settings
from app.db import get_supabase


class SupabaseHTTPTest(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        path = os.environ.get("MILESTONE1_SUPABASE_CONFIG")
        if not path:
            raise unittest.SkipTest("Set MILESTONE1_SUPABASE_CONFIG to disposable local Supabase status JSON (see docs/milestone-1-review.md)")
        if os.environ.get("MILESTONE1_DISPOSABLE_SUPABASE") != "1":
            raise RuntimeError("Explicit MILESTONE1_DISPOSABLE_SUPABASE=1 required")
        cls.cfg = json.loads(Path(path).read_text())
        for key in ("API_URL", "DB_URL"):
            if urlparse(cls.cfg[key]).hostname not in ("localhost", "127.0.0.1", "::1"):
                raise RuntimeError("Only a disposable LOCAL Supabase stack is permitted")

    def sql(self, sql):
        r = subprocess.run(["psql", "-X", "-qAt", "-v", "ON_ERROR_STOP=1", self.cfg["DB_URL"], "-c", sql], capture_output=True, text=True, timeout=30)
        if r.returncode:
            raise RuntimeError(r.stderr)
        return r.stdout.strip()

    async def asyncSetUp(self):
        self.http = httpx.AsyncClient(base_url=self.cfg["API_URL"])
        self.addAsyncCleanup(self.http.aclose)
        self.admin = {"apikey": self.cfg["SERVICE_ROLE_KEY"], "Authorization": f"Bearer {self.cfg['SERVICE_ROLE_KEY']}"}
        self.users = []
        self.addAsyncCleanup(self.cleanup_users)
        self.tokens = []
        for _ in range(2):
            email, password = f"fixture-{uuid4()}@example.test", str(uuid4())
            r = await self.http.post("/auth/v1/admin/users", headers=self.admin, json={"email": email, "password": password, "email_confirm": True})
            self.assertEqual(r.status_code, 200, r.status_code)
            self.users.append(r.json()["id"])
            r = await self.http.post("/auth/v1/token?grant_type=password", headers={"apikey": self.cfg["ANON_KEY"]}, json={"email": email, "password": password})
            self.assertEqual(r.status_code, 200)
            self.tokens.append(r.json()["access_token"])
        r = await self.http.post("/auth/v1/signup", headers={"apikey": self.cfg["ANON_KEY"]}, json={})
        self.assertEqual(r.status_code, 200)
        self.users.append(r.json()["user"]["id"])
        self.tokens.append(r.json()["access_token"])
        self.job = str(uuid4())
        self.guest_job = str(uuid4())
        for job, user in ((self.job, self.users[0]), (self.guest_job, self.users[2])):
            self.sql(f"INSERT INTO public.searches(id,user_id,invention_idea,status) VALUES ('{job}','{user}','Synthetic irrigation controller with humidity sensors','completed'); INSERT INTO public.search_results(search_id,claims_analysis) VALUES ('{job}','[]'); INSERT INTO public.patents(search_id,patent_id,title,abstract) VALUES ('{job}','fixture','Fixture','Synthetic fixture');")
        db = await create_async_client(self.cfg["API_URL"], self.cfg["SERVICE_ROLE_KEY"])
        self.db = db
        self.addAsyncCleanup(db.postgrest.aclose)
        self.addAsyncCleanup(db.auth.close)
        app = FastAPI()
        app.include_router(router, prefix="/api")
        app.include_router(billing_router, prefix="/api/stripe")
        app.dependency_overrides[get_supabase] = lambda: db
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture")
        self.addAsyncCleanup(self.client.aclose)
        self.graph = self.enterContext(patch("app.worker.run_claim", new=AsyncMock()))
        self.model = self.enterContext(patch("app.api.routes.create_chat_completion", new=AsyncMock(return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"claims":[],"invention_name":"Fixture"}'))]))))
        self.lens = self.enterContext(patch("app.agents.nodes.fetcher.fetch_lens_patents", new=AsyncMock()))
        self.serp = self.enterContext(patch("app.agents.nodes.fetcher.fetch_serpapi_patents", new=AsyncMock()))
        # Higher anonymous Auth rate limit is configured only in this test stack.

    async def cleanup_users(self):
        for user in self.users:
            self.sql(f"DELETE FROM public.usage_reservations WHERE user_id='{user}'")
            await self.http.delete(f"/auth/v1/admin/users/{user}", headers=self.admin)

    def headers(self, token):
        return {"Authorization": f"Bearer {token}"} if token else {}

    async def request(self, method, path, token, body=None):
        if path == "/api/jobs" and isinstance(body, dict):
            body = {"submission_key": str(uuid.uuid4()), **body}
        return await self.client.request(method, path, headers=self.headers(token), json=body)

    def no_work(self):
        self.model.assert_not_awaited()
        self.graph.assert_not_awaited()
        self.lens.assert_not_awaited()
        self.serp.assert_not_awaited()

    async def test_actual_auth_denials_and_owner_guest_access(self):
        enc = lambda value: base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=")
        message = enc({"alg": "HS256", "typ": "JWT"}) + b"." + enc({"sub": self.users[0], "role": "authenticated", "aud": "authenticated", "exp": int(time.time())-60})
        expired = (message+b"."+base64.urlsafe_b64encode(hmac.new(self.cfg["JWT_SECRET"].encode(), message, hashlib.sha256).digest()).rstrip(b"=")).decode()
        paths = [("GET", f"/api/jobs/{self.job}", None), ("GET", f"/api/jobs/{self.job}/analyze-claims", None), ("POST", f"/api/jobs/{self.job}/analyze-claims", None), ("POST", f"/api/jobs/{self.job}/ideate", {"white_space_title":"Gap", "white_space_description":"Synthetic gap"})]
        for token, code in ((None,401),("invalid",401),(expired,401),(self.tokens[1],404),(self.tokens[2],404)):
            for method, path, body in paths:
                self.assertEqual((await self.request(method,path,token,body)).status_code, code)
        self.no_work()
        self.assertEqual(self.sql(f"SELECT count(*) FROM public.usage_reservations WHERE user_id='{self.users[0]}'"), "0")
        for token, job in ((self.tokens[0],self.job),(self.tokens[2],self.guest_job)):
            self.assertEqual((await self.request("GET",f"/api/jobs/{job}",token)).status_code,200)
            self.assertEqual((await self.request("POST",f"/api/jobs/{job}/analyze-claims",token)).status_code,200)

    async def test_browser_postgrest_rls_and_rpc_permissions(self):
        for table, key in (("searches","id"),("search_results","search_id"),("patents","search_id")):
            guest_read = await self.http.get(f"/rest/v1/{table}?{key}=eq.{self.guest_job}", headers={"apikey":self.cfg["ANON_KEY"], **self.headers(self.tokens[2])})
            self.assertEqual(guest_read.status_code,200)
            self.assertEqual(len(guest_read.json()),1)
            for token, visible in ((self.tokens[0],True),(self.tokens[1],False),(self.tokens[2],False),(self.cfg["ANON_KEY"],False)):
                headers={"apikey":self.cfg["ANON_KEY"], **self.headers(token)}
                url=f"/rest/v1/{table}?{key}=eq.{self.job}"
                r=await self.http.get(url,headers=headers)
                self.assertEqual(r.status_code,200)
                self.assertEqual(bool(r.json()),visible)
                for method,payload in (("PATCH",{key:self.job}),("DELETE",None),("POST",{key:self.job})):
                    r=await self.http.request(method,url,headers=headers,json=payload)
                    self.assertIn(r.status_code,(401,403))
        for token in (self.tokens[0],self.tokens[1],self.tokens[2],self.cfg["ANON_KEY"]):
            headers={"apikey":self.cfg["ANON_KEY"],**self.headers(token)}
            for fn,args in (("claim_analysis",{"p_lease_seconds":60,"p_max_active":99}),("read_analysis_status",{"p_search_id":self.job,"p_user_id":self.users[0]}),("publish_analysis",{"p_search_id":self.job,"p_token":self.job}),("admit_analysis",{"p_user_id":self.users[0],"p_submission_key":self.job,"p_payload":{},"p_execution_inputs":{},"p_free_limit":999,"p_pro_limit":999,"p_global_limit":999,"p_window_seconds":1}),("finalize_analysis",{"p_search_id":self.job,"p_result":{},"p_patents":[]}),("paid_usage_snapshot",{"p_user_id":self.users[0],"p_window_seconds":1}),("reserve_paid_operation",{"p_user_id":self.users[0],"p_operation":"claims","p_free_limit":999,"p_pro_limit":999,"p_global_limit":999,"p_window_seconds":1})):
                r=await self.http.post(f"/rest/v1/rpc/{fn}",headers=headers,json=args)
                self.assertIn(r.status_code,(401,403))
            r=await self.http.patch(f"/rest/v1/subscriptions?user_id=eq.{self.users[0]}",headers=headers,json={"plan":"pro"})
            self.assertIn(r.status_code,(401,403))
        self.no_work()

    async def test_display_counts_failed_paid_attempts_with_enforcement_window(self):
        with patch.object(settings,"quota_window_days",7), patch.object(settings,"free_claims_limit",1):
            r=await self.request("GET","/api/stripe/subscription-status",self.tokens[0])
            self.assertEqual(r.status_code,200)
            self.assertEqual(r.json()["usage"]["job"]["used"],0)  # Existing fixture search isn't a reservation.
            self.model.side_effect=RuntimeError("Synthetic provider failure")
            self.assertEqual((await self.request("POST",f"/api/jobs/{self.job}/analyze-claims",self.tokens[0])).status_code,500)
            r=await self.request("GET","/api/stripe/subscription-status",self.tokens[0])
            self.assertEqual(r.json()["window_seconds"],604800)
            self.assertEqual(r.json()["usage"]["claims"],{"used":1,"limit":1,"remaining":0})
            self.assertEqual((await self.request("POST",f"/api/jobs/{self.job}/analyze-claims",self.tokens[0])).status_code,402)
            self.assertEqual(self.model.await_count,1)

    async def test_concurrent_last_unit_through_auth_and_postgrest(self):
        for operation,path,body in (("job","/api/jobs",{"invention_idea":"Synthetic irrigation controller with humidity sensors"}),("claims",f"/api/jobs/{self.job}/analyze-claims",None),("ideation",f"/api/jobs/{self.job}/ideate",{"white_space_title":"Gap","white_space_description":"Synthetic gap"})):
            self.model.reset_mock(); self.graph.reset_mock()
            with patch.object(settings,f"free_{operation}_limit",1):
                responses=await asyncio.gather(*(self.request("POST",path,self.tokens[0],body) for _ in range(8)))
            self.assertEqual(sum(r.status_code in (200,202) for r in responses),1)
            self.assertEqual(sum(r.status_code==402 for r in responses),7)
            self.assertEqual(self.model.await_count+self.graph.await_count,0 if operation == "job" else 1)

    async def test_quota_outage_through_postgrest_launches_no_work(self):
        self.sql("ALTER TABLE public.usage_reservations RENAME TO usage_reservations_outage")
        try:
            for path,body in (("/api/jobs",{"invention_idea":"Synthetic irrigation controller with humidity sensors"}),(f"/api/jobs/{self.job}/analyze-claims",None),(f"/api/jobs/{self.job}/ideate",{"white_space_title":"Gap","white_space_description":"Synthetic gap"})):
                self.assertEqual((await self.request("POST",path,self.tokens[0],body)).status_code,503)
            self.no_work()
        finally:
            self.sql("ALTER TABLE public.usage_reservations_outage RENAME TO usage_reservations")

    async def test_saved_report_through_sdk_and_browser_rls_cached_reopening_is_free(self):
        from test_saved_results import state, REPORT
        final = state(); final["search_id"] = self.job
        final.update(retrieval_outcome="partial", coverage_warnings=["Partial coverage fixture"])
        lease_token = str(uuid4())
        self.sql(f"UPDATE public.searches SET status='running' WHERE id='{self.job}'; INSERT INTO public.analysis_queue(search_id,user_id,submission_key,payload,execution_inputs,state,lease_token,lease_expires_at) VALUES ('{self.job}','{self.users[0]}','{lease_token}','{{}}','{{}}','running','{lease_token}',clock_timestamp()+interval '60 seconds')")
        with patch("app.worker.build_graph", return_value=SimpleNamespace(ainvoke=AsyncMock(return_value=final))):
            await run_saved_graph(self.db,dict(search_id=self.job,lease_token=lease_token,state="running",payload=dict(invention_idea="Synthetic invention",jurisdiction="all"),execution_inputs=dict(version=2,mock_mode=True,serpapi_enabled=False,groq_model="fixture")))
        for token, visible in ((self.tokens[0],True),(self.tokens[1],False),(self.tokens[2],False),(self.cfg["ANON_KEY"],False)):
            r = await self.http.get(f"/rest/v1/search_results?search_id=eq.{self.job}",headers={"apikey":self.cfg["ANON_KEY"],**self.headers(token)})
            self.assertEqual(r.status_code,200)
            self.assertEqual(bool(r.json()),visible)
            if visible:
                self.assertEqual(r.json()[0]["final_report"],REPORT)
                self.assertEqual(r.json()[0]["white_space_analysis"],"Separate gaps")
                self.assertEqual(r.json()[0]["coverage_warnings"],["Partial coverage fixture"])
                evidence=await self.request("GET",f"/api/jobs/{self.job}/evidence",token)
                self.assertEqual(evidence.json()["patents"][0]["evidence"],final["deduped_patents"][0]["evidence"])
        for _ in range(2):
            status=await self.request("GET",f"/api/jobs/{self.job}",self.tokens[0])
            self.assertEqual(status.json()["status"],"completed")
            cached=await self.request("GET",f"/api/jobs/{self.job}/analyze-claims",self.tokens[0])
            self.assertEqual(cached.json(),{"claims":[]})
        self.assertEqual(self.sql(f"SELECT count(*) FROM public.usage_reservations WHERE user_id='{self.users[0]}'"),"0")
        self.no_work()

    async def test_saved_evidence_actual_auth_rls_and_zero_paid_calls(self):
        from test_evidence_sql import evidence_output
        from test_milestone1_sql import literal
        evidence = evidence_output()["patents"][0]["evidence"]
        self.sql(f"UPDATE public.patents SET evidence={literal(json.dumps(evidence))}::jsonb WHERE search_id='{self.job}'")
        for _ in range(2):
            r = await self.request("GET", f"/api/jobs/{self.job}/evidence", self.tokens[0])
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["patents"][0]["evidence"], evidence)
        for token, expected in ((None,401),("invalid",401),(self.tokens[1],404),(self.tokens[2],404)):
            r = await self.request("GET", f"/api/jobs/{self.job}/evidence", token)
            self.assertEqual(r.status_code, expected)
        for token, visible in ((self.tokens[0],True),(self.tokens[1],False),(self.cfg["ANON_KEY"],False)):
            headers={"apikey":self.cfg["ANON_KEY"],**self.headers(token)}
            r=await self.http.get(f"/rest/v1/patents?search_id=eq.{self.job}&select=evidence",headers=headers)
            self.assertEqual(r.status_code,200)
            self.assertEqual(bool(r.json()),visible)
            r=await self.http.patch(f"/rest/v1/patents?search_id=eq.{self.job}",headers=headers,json={"evidence":None})
            self.assertIn(r.status_code,(200,204,401,403))
        self.assertEqual(json.loads(self.sql(f"SELECT evidence FROM public.patents WHERE search_id='{self.job}'")),evidence)
        guest=await self.request("GET",f"/api/jobs/{self.guest_job}/evidence",self.tokens[2])
        self.assertEqual(guest.status_code,200)
        self.assertEqual(guest.json()["patents"][0]["evidence_status"],"legacy_unknown")
        self.assertEqual(self.sql(f"SELECT count(*) FROM public.usage_reservations WHERE user_id='{self.users[0]}'"),"0")
        self.no_work()

    async def test_insufficient_evidence_denies_generation_before_reservation(self):
        self.sql(f"UPDATE public.searches SET status='insufficient_evidence' WHERE id='{self.job}'")
        for path,body in ((f"/api/jobs/{self.job}/analyze-claims",None),(f"/api/jobs/{self.job}/ideate",{"white_space_title":"Gap","white_space_description":"Synthetic gap"})):
            self.assertEqual((await self.request("POST",path,self.tokens[0],body)).status_code,409)
        self.assertEqual(self.sql(f"SELECT count(*) FROM public.usage_reservations WHERE user_id='{self.users[0]}'"),"0")
        self.no_work()

    async def test_durable_admission_response_loss_owner_scope_and_worker_sdk(self):
        from app.services.jobs import rpc
        from test_saved_results import state, REPORT
        body={'invention_idea':'Synthetic durable irrigation invention','jurisdiction':'us','submission_key':str(uuid4())}
        # The first committed response is deliberately discarded, then retried concurrently.
        first=await self.request('POST','/api/jobs',self.tokens[0],body)
        self.assertEqual(first.status_code,202,first.text)
        with patch.object(settings,'free_job_limit',1):
            responses=await asyncio.gather(*(self.request('POST','/api/jobs',self.tokens[0],body) for _ in range(8)))
        job=first.json()['job_id']
        self.assertTrue(all(r.status_code==202 and r.json()['job_id']==job for r in responses))
        self.assertEqual(self.sql(f"SELECT count(*) FROM public.usage_reservations WHERE user_id='{self.users[0]}'"),'1')
        self.assertEqual((await self.request('POST','/api/jobs',self.tokens[0],{**body,'jurisdiction':'ep'})).status_code,409)
        other=await self.request('POST','/api/jobs',self.tokens[1],body)
        self.assertEqual(other.status_code,202);self.assertNotEqual(other.json()['job_id'],job)
        self.assertEqual((await self.request('GET',f'/api/jobs/{job}',self.tokens[1])).status_code,404)
        self.no_work()
        claimed=await rpc(self.db,'claim_analysis',{'p_lease_seconds':60,'p_max_active':1})
        self.assertEqual(claimed['search_id'],job)
        import copy
        final=copy.deepcopy(state())
        for patent in final["deduped_patents"]:
            for observation in patent["evidence"]["observations"]:
                observation["requested_jurisdiction"] = body["jurisdiction"]
        with patch('app.worker.build_graph',return_value=SimpleNamespace(ainvoke=AsyncMock(return_value=final))):
            await run_saved_graph(self.db,claimed)
        self.assertEqual((await self.request('GET',f'/api/jobs/{job}',self.tokens[0])).json()['status'],'completed')
        for token,visible in ((self.tokens[0],True),(self.tokens[1],False),(self.tokens[2],False),(self.cfg['ANON_KEY'],False)):
            headers={'apikey':self.cfg['ANON_KEY'],**self.headers(token)}
            r=await self.http.get(f'/rest/v1/search_results?search_id=eq.{job}',headers=headers)
            self.assertEqual(r.status_code,200);self.assertEqual(bool(r.json()),visible)
            if visible:self.assertEqual(r.json()[0]['final_report'],REPORT)
            r=await self.http.get('/rest/v1/analysis_queue',headers=headers)
            self.assertIn(r.status_code,(401,403))
        # Original legacy RPC and direct service writes cannot bypass the fence.
        r=await self.http.post('/rest/v1/rpc/finalize_analysis',headers=self.admin,json={'p_search_id':job,'p_result':{},'p_patents':[]})
        self.assertIn(r.status_code,(401,403))
        r=await self.http.patch(f'/rest/v1/searches?id=eq.{job}',headers=self.admin,json={'status':'failed'})
        self.assertEqual(r.status_code,400)
        # Claims-cache write remains authorized and independently metered.
        self.assertEqual((await self.request('POST',f'/api/jobs/{job}/analyze-claims',self.tokens[0])).status_code,200)

    async def test_status_expires_dead_worker_without_starting_paid_work(self):
        from app.services.jobs import rpc
        response=await self.request('POST','/api/jobs',self.tokens[2],{'invention_idea':'Synthetic anonymous durable invention'})
        self.assertEqual(response.status_code,202,response.text)
        job=response.json()['job_id']
        claim=await rpc(self.db,'claim_analysis',{'p_lease_seconds':60,'p_max_active':1})
        self.assertEqual(claim['search_id'],job)
        self.sql(f"UPDATE public.analysis_queue SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE search_id='{job}'")
        self.assertEqual((await self.request('GET',f'/api/jobs/{job}',self.tokens[0])).status_code,404)
        self.assertEqual(self.sql(f"SELECT status FROM public.searches WHERE id='{job}'"),'running')
        for _ in range(2):
            status=await self.request('GET',f'/api/jobs/{job}',self.tokens[2])
            self.assertEqual(status.json()['status'],'interrupted')
        self.assertEqual(self.sql(f"SELECT count(*) FROM public.usage_reservations WHERE user_id='{self.users[2]}'"),'1')
        self.no_work()
