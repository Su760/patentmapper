"""Checkout eligibility is stricter than verified anonymous analysis access."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI

from app.api.stripe_routes import router
from app.db import get_supabase


class CheckoutTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.user = SimpleNamespace(id="00000000-0000-0000-0000-000000000001", email="fixture@example.test", is_anonymous=False)
        db = SimpleNamespace(auth=SimpleNamespace(get_user=AsyncMock(return_value=SimpleNamespace(user=self.user))))
        app = FastAPI()
        app.include_router(router, prefix="/api/stripe")
        app.dependency_overrides[get_supabase] = lambda: db
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture")
        self.addAsyncCleanup(self.client.aclose)
        self.stripe = self.enterContext(patch("app.api.stripe_routes.stripe.checkout.Session.create", return_value=SimpleNamespace(url="https://checkout.stripe.test/fixture")))

    async def test_verified_anonymous_user_is_denied_before_stripe(self):
        self.user.is_anonymous = True
        r = await self.client.post("/api/stripe/create-checkout-session", headers={"Authorization":"Bearer fixture"})
        self.assertEqual(r.status_code,403)
        self.assertIn("permanent account",r.json()["detail"])
        self.stripe.assert_not_called()

    async def test_registered_user_can_create_checkout(self):
        r = await self.client.post("/api/stripe/create-checkout-session", headers={"Authorization":"Bearer fixture"})
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.json(),{"checkout_url":"https://checkout.stripe.test/fixture"})
        self.stripe.assert_called_once()
        self.assertEqual(self.stripe.call_args.kwargs["client_reference_id"], self.user.id)

    async def test_missing_credentials_do_not_call_stripe(self):
        r = await self.client.post("/api/stripe/create-checkout-session")
        self.assertEqual(r.status_code,401)
        self.stripe.assert_not_called()
