"""
Patent Landscape Mapper — FastAPI application entry point
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.api.stripe_routes import router as stripe_router
from app.core.config import settings
from app.db import get_supabase

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Patent Landscape Mapper backend")
    logger.info("MOCK_MODE=%s", settings.mock_mode)
    logger.info(
        "Supabase migration — run once in SQL editor if not done:\n"
        "CREATE TABLE IF NOT EXISTS subscriptions (\n"
        "  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),\n"
        "  user_id UUID NOT NULL UNIQUE,\n"
        "  stripe_customer_id TEXT,\n"
        "  stripe_subscription_id TEXT,\n"
        "  plan TEXT NOT NULL DEFAULT 'free',\n"
        "  status TEXT NOT NULL DEFAULT 'active',\n"
        "  current_period_end TIMESTAMPTZ,\n"
        "  created_at TIMESTAMPTZ DEFAULT NOW(),\n"
        "  updated_at TIMESTAMPTZ DEFAULT NOW()\n"
        ");\n"
        "ALTER TABLE subscriptions ENABLE ROW LEVEL SECURITY;\n"
        'CREATE POLICY "Users can read own subscription" ON subscriptions FOR SELECT USING (auth.uid() = user_id);'
    )

    logger.info(
        "MIGRATION NEEDED: ALTER TABLE search_results ADD COLUMN IF NOT EXISTS citation_links JSONB DEFAULT '[]';"
    )

    if settings.supabase_url:
        try:
            supabase = await get_supabase()
            # Quick connectivity check
            await supabase.table("searches").select("id").limit(1).execute()
            logger.info("Supabase connection OK")
        except Exception as exc:
            logger.warning("Supabase connection check failed: %s", exc)
    else:
        logger.warning("SUPABASE_URL not set — Supabase disabled")

    yield

    # Shutdown
    logger.info("Shutting down Patent Landscape Mapper backend")


app = FastAPI(
    title="Patent Landscape Mapper API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")
app.include_router(stripe_router, prefix="/api/stripe")
