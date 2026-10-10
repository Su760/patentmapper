"""Display must use the reservation ledger, never inferred search counts."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI

from app.api.stripe_routes import router
from app.core.config import settings
from app.db import get_supabase
from test_private_analyses import SecurityDB, OWNER


class UsageStatusTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = SecurityDB()
        self.execute = AsyncMock(return_value=SimpleNamespace(data={
            "plan": "free", "used": {"job": 2, "claims": 1, "ideation": 4},
            "window_seconds": 604800, "as_of": "2026-10-02T00:00:00Z",
        }))
        from unittest.mock import Mock
        self.db.rpc = self.rpc = Mock(return_value=SimpleNamespace(execute=self.execute))
        app = FastAPI()
        app.include_router(router, prefix="/api/stripe")
        app.dependency_overrides[get_supabase] = lambda: self.db
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture")
        self.addAsyncCleanup(self.client.aclose)

    async def test_display_uses_authoritative_reservations_and_configured_window(self):
        with patch.object(settings, "quota_window_days", 7), patch.object(settings, "free_job_limit", 4):
            r = await self.client.get("/api/stripe/subscription-status", headers={"Authorization": "Bearer owner"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["usage"]["job"], {"used": 2, "limit": 4, "remaining": 2})
        self.assertEqual(r.json()["window_seconds"], 604800)
        self.rpc.assert_called_once_with("paid_usage_snapshot", {"p_user_id": OWNER, "p_window_seconds": 604800})
        self.assertEqual(self.db.reads, [])
        self.assertEqual(self.db.reservations, [])

    async def test_store_failure_and_malformed_snapshot_are_not_free_zero(self):
        for data in (None, {}, {"plan": "unlimited"}, {"plan": "free", "used": {}}):
            self.execute.return_value = SimpleNamespace(data=data)
            r = await self.client.get("/api/stripe/subscription-status", headers={"Authorization": "Bearer owner"})
            self.assertEqual(r.status_code, 503)
        self.execute.side_effect = RuntimeError("store unavailable")
        r = await self.client.get("/api/stripe/subscription-status", headers={"Authorization": "Bearer owner"})
        self.assertEqual(r.status_code, 503)

    async def test_denied_credentials_do_not_read_usage(self):
        for token in (None, "invalid", "expired"):
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            r = await self.client.get("/api/stripe/subscription-status", headers=headers)
            self.assertEqual(r.status_code, 401)
        self.rpc.assert_not_called()
