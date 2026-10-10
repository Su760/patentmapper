-- Apply with an administrative migration role. No data is deleted or assigned an owner.
BEGIN;

CREATE TABLE IF NOT EXISTS public.searches (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid REFERENCES auth.users(id) ON DELETE CASCADE,
  invention_idea text NOT NULL,
  status text NOT NULL DEFAULT 'processing',
  current_step text,
  created_at timestamptz DEFAULT now(),
  error_message text
);
CREATE TABLE IF NOT EXISTS public.search_results (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  search_id uuid UNIQUE REFERENCES public.searches(id) ON DELETE CASCADE,
  clusters jsonb,
  white_space_analysis text,
  citation_links jsonb DEFAULT '[]'::jsonb,
  claims_analysis jsonb,
  pdf_url text,
  created_at timestamptz DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.patents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  search_id uuid REFERENCES public.searches(id) ON DELETE CASCADE,
  patent_id text,
  title text,
  abstract text,
  assignee text,
  similarity_score double precision,
  url text
);
CREATE TABLE IF NOT EXISTS public.subscriptions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL UNIQUE,
  stripe_customer_id text,
  stripe_subscription_id text,
  plan text NOT NULL DEFAULT 'free',
  status text NOT NULL DEFAULT 'active',
  current_period_end timestamptz,
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now()
);

-- Existing deployments were provisioned from older README/CLAUDE snippets.
ALTER TABLE public.searches ADD COLUMN IF NOT EXISTS user_id uuid REFERENCES auth.users(id) ON DELETE CASCADE;
ALTER TABLE public.search_results ADD COLUMN IF NOT EXISTS citation_links jsonb DEFAULT '[]'::jsonb;
ALTER TABLE public.search_results ADD COLUMN IF NOT EXISTS claims_analysis jsonb;
CREATE INDEX IF NOT EXISTS searches_user_created_idx ON public.searches(user_id, created_at);
CREATE INDEX IF NOT EXISTS patents_search_idx ON public.patents(search_id);

-- NOT VALID retains legacy ownerless rows but forbids new ownerless rows.
-- Legacy searches and their children remain invisible to every browser user.
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_constraint WHERE conrelid='public.searches'::regclass AND conname='searches_owner_required') THEN
    ALTER TABLE public.searches ADD CONSTRAINT searches_owner_required CHECK (user_id IS NOT NULL) NOT VALID;
  END IF;
END $$;

-- Permissive policies combine with OR. Replace old policies on these tables so
-- an earlier broad policy cannot defeat the owner checks below.
DO $$ DECLARE policy_row record; BEGIN
  FOR policy_row IN SELECT schemaname, tablename, policyname FROM pg_policies
    WHERE schemaname='public' AND tablename IN ('searches','search_results','patents','subscriptions')
  LOOP
    EXECUTE format('DROP POLICY %I ON %I.%I', policy_row.policyname, policy_row.schemaname, policy_row.tablename);
  END LOOP;
END $$;

ALTER TABLE public.searches ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.search_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.patents ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.subscriptions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.searches, public.search_results, public.patents, public.subscriptions FROM PUBLIC, anon, authenticated;
GRANT SELECT ON public.searches, public.search_results, public.patents, public.subscriptions TO anon, authenticated;
GRANT ALL ON public.searches, public.search_results, public.patents, public.subscriptions TO service_role;

-- Verified Supabase anonymous sessions use authenticated + an actual auth.uid().
-- The anon database role (signed out) has no applicable SELECT policy.
CREATE POLICY searches_owner_read ON public.searches FOR SELECT TO authenticated
  USING ((SELECT auth.uid()) = user_id);
CREATE POLICY results_owner_read ON public.search_results FOR SELECT TO authenticated
  USING (EXISTS (SELECT 1 FROM public.searches s WHERE s.id=search_id AND s.user_id=(SELECT auth.uid())));
CREATE POLICY patents_owner_read ON public.patents FOR SELECT TO authenticated
  USING (EXISTS (SELECT 1 FROM public.searches s WHERE s.id=search_id AND s.user_id=(SELECT auth.uid())));
CREATE POLICY subscription_owner_read ON public.subscriptions FOR SELECT TO authenticated
  USING ((SELECT auth.uid()) = user_id);

COMMIT;
