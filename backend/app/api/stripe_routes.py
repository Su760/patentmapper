"""
Stripe billing endpoints.
POST /api/stripe/create-checkout-session — start a Pro subscription checkout
GET  /api/stripe/subscription-status    — check current plan for the authed user
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from supabase import AsyncClient, create_async_client

from app.core.config import settings
from app.db import get_supabase

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Auth helper ────────────────────────────────────────────────────────────────


async def _get_user(authorization: Optional[str], supabase: AsyncClient) -> Any:
    """Validate Bearer JWT and return the Supabase user object."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
    jwt = authorization.removeprefix("Bearer ")
    try:
        resp = await supabase.auth.get_user(jwt)
        if not resp.user:
            raise HTTPException(status_code=401, detail="Invalid token")
        return resp.user
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")


# ── Endpoints ──────────────────────────────────────────────────────────────────


@router.post("/create-checkout-session")
async def create_checkout_session(
    authorization: Optional[str] = Header(default=None),
    supabase: AsyncClient = Depends(get_supabase),
) -> Dict[str, Any]:
    """Create a Stripe Checkout Session for the Pro plan and return its URL."""
    user = await _get_user(authorization, supabase)
    stripe.api_key = settings.stripe_secret_key

    session = await asyncio.to_thread(
        stripe.checkout.Session.create,
        payment_method_types=["card"],
        mode="subscription",
        line_items=[{"price": settings.stripe_pro_price_id, "quantity": 1}],
        success_url="http://localhost:3000/dashboard?upgraded=true",
        cancel_url="http://localhost:3000/pricing",
        client_reference_id=str(user.id),
        customer_email=user.email,
    )
    logger.info("[stripe] checkout session created for user %s", user.id)
    return {"checkout_url": session.url}


@router.get("/subscription-status")
async def subscription_status(
    authorization: Optional[str] = Header(default=None),
    supabase: AsyncClient = Depends(get_supabase),
) -> Dict[str, Any]:
    """Return the current plan for the authenticated user."""
    user = await _get_user(authorization, supabase)

    try:
        result = (
            await supabase.table("subscriptions")
            .select("plan, status")
            .eq("user_id", str(user.id))
            .limit(1)
            .execute()
        )
        sub_data = result.data[0] if result.data else None
    except Exception:
        sub_data = None

    if (
        sub_data is not None
        and sub_data.get("plan") == "pro"
        and sub_data.get("status") == "active"
    ):
        return {"plan": "pro"}

    # Count searches in the past 30 days
    try:
        since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        count_result = (
            await supabase.table("searches")
            .select("id", count="exact")
            .eq("user_id", str(user.id))
            .gte("created_at", since)
            .execute()
        )
        searches_used = count_result.count or 0
    except Exception:
        searches_used = 0
    return {"plan": "free", "searches_used": searches_used}


@router.post("/webhook")
async def stripe_webhook(request: Request) -> Any:
    """Handle Stripe webhook events. Uses raw body bytes for signature verification."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    stripe.api_key = settings.stripe_secret_key

    try:
        event = await asyncio.to_thread(
            stripe.Webhook.construct_event,
            payload,
            sig_header,
            settings.stripe_webhook_secret,
        )
    except stripe.SignatureVerificationError:
        logger.warning("[webhook] signature verification failed")
        return Response(content="Invalid signature", status_code=400)

    # Service-role client bypasses RLS for writes
    admin = await create_async_client(settings.supabase_url, settings.supabase_service_key)

    if event["type"] == "checkout.session.completed":
        data = dict(event["data"]["object"])
        user_id = data.get("client_reference_id")
        customer_id = data.get("customer")
        subscription_id = data.get("subscription")
        if user_id:
            await admin.table("subscriptions").upsert(
                {
                    "user_id": user_id,
                    "stripe_customer_id": customer_id,
                    "stripe_subscription_id": subscription_id,
                    "plan": "pro",
                    "status": "active",
                },
                on_conflict="user_id",
            ).execute()
            logger.info("[webhook] user %s upgraded to pro", user_id)

    elif event["type"] == "customer.subscription.deleted":
        sub_id = dict(event["data"]["object"]).get("id")
        if sub_id:
            await admin.table("subscriptions").update(
                {"plan": "free", "status": "cancelled"}
            ).eq("stripe_subscription_id", sub_id).execute()
            logger.info("[webhook] subscription %s cancelled", sub_id)

    return {"received": True}
