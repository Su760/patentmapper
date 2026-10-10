"""
Stripe billing endpoints.
POST /api/stripe/create-checkout-session — start a Pro subscription checkout
GET  /api/stripe/subscription-status    — check current plan for the authed user
"""
import asyncio
import logging
from typing import Any, Dict, Optional

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from supabase import AsyncClient, create_async_client

from app.core.config import settings
from app.core.security import validate_user
from app.db import get_supabase
from app.services.usage import usage_status

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Auth helper ────────────────────────────────────────────────────────────────


async def _get_user(authorization: Optional[str], supabase: AsyncClient) -> Any:
    """Validate Bearer JWT and return the Supabase user object."""
    return await validate_user(authorization, supabase)


# ── Endpoints ──────────────────────────────────────────────────────────────────


@router.post("/create-checkout-session")
async def create_checkout_session(
    authorization: Optional[str] = Header(default=None),
    supabase: AsyncClient = Depends(get_supabase),
) -> Dict[str, Any]:
    """Create a Stripe Checkout Session for the Pro plan and return its URL."""
    user = await _get_user(authorization, supabase)
    if user.is_anonymous:
        raise HTTPException(403, "Sign in or create a permanent account before upgrading. Anonymous sessions cannot purchase a plan.")
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

    return await usage_status(supabase, str(user.id))


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
