BEGIN;

-- Retain consumed usage even when a user or search is deleted. Deletion must not
-- reset the global budget. linked_search_id also makes legacy seeding idempotent.
CREATE TABLE IF NOT EXISTS public.usage_reservations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid REFERENCES auth.users(id) ON DELETE SET NULL,
  operation text NOT NULL CHECK (operation IN ('job','claims','ideation')),
  linked_search_id uuid UNIQUE,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS usage_user_operation_time_idx ON public.usage_reservations(user_id, operation, created_at);
CREATE INDEX IF NOT EXISTS usage_time_idx ON public.usage_reservations(created_at);
ALTER TABLE public.usage_reservations ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.usage_reservations FROM PUBLIC, anon, authenticated;
GRANT ALL ON public.usage_reservations TO service_role;

-- Existing searches consume job usage without exposing or adopting ownerless data.
INSERT INTO public.usage_reservations(user_id, operation, linked_search_id, created_at)
  SELECT user_id, 'job', id, coalesce(created_at, now()) FROM public.searches
  ON CONFLICT (linked_search_id) DO NOTHING;

CREATE OR REPLACE FUNCTION public.reserve_paid_operation(
  p_user_id uuid,
  p_operation text,
  p_free_limit integer,
  p_pro_limit integer,
  p_global_limit integer,
  p_window_seconds integer,
  p_search_id uuid DEFAULT NULL
) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
  window_start timestamptz;
  user_limit integer;
  anonymous_user boolean;
BEGIN
  IF p_user_id IS NULL OR p_operation IS NULL OR p_operation NOT IN ('job','claims','ideation')
     OR p_free_limit IS NULL OR p_free_limit < 0 OR p_pro_limit IS NULL OR p_pro_limit < 0
     OR p_global_limit IS NULL OR p_global_limit < 0 OR p_window_seconds IS NULL OR p_window_seconds <= 0 THEN
    RAISE EXCEPTION 'Invalid usage reservation parameters';
  END IF;
  IF p_operation='job' AND p_search_id IS NULL THEN
    RAISE EXCEPTION 'A job reservation requires its search ID';
  END IF;
  IF p_operation<>'job' AND p_search_id IS NOT NULL THEN
    RAISE EXCEPTION 'Only job reservations may link a search ID';
  END IF;

  -- A single transaction-scoped lock protects BOTH per-user and global admission
  -- across processes, users and operations. Counts and insertion happen together.
  PERFORM pg_advisory_xact_lock(726183940221::bigint);
  window_start := clock_timestamp() - make_interval(secs => p_window_seconds);
  SELECT u.is_anonymous INTO anonymous_user FROM auth.users u WHERE u.id=p_user_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'Unknown usage owner'; END IF;

  user_limit := p_free_limit;
  IF NOT anonymous_user AND EXISTS (
    SELECT 1 FROM public.subscriptions s WHERE s.user_id=p_user_id AND s.plan='pro' AND s.status='active'
      AND (s.current_period_end IS NULL OR s.current_period_end > clock_timestamp())
  ) THEN user_limit := p_pro_limit; END IF;

  IF (SELECT count(*) FROM public.usage_reservations r
      WHERE r.user_id=p_user_id AND r.operation=p_operation AND r.created_at>=window_start) >= user_limit THEN
    RETURN 'user_limit';
  END IF;
  IF (SELECT count(*) FROM public.usage_reservations r WHERE r.created_at>=window_start) >= p_global_limit THEN
    RETURN 'global_limit';
  END IF;
  INSERT INTO public.usage_reservations(user_id,operation,linked_search_id,created_at)
    VALUES (p_user_id,p_operation,p_search_id,clock_timestamp());
  RETURN 'allowed';
END $$;

-- Browser users cannot pick their own limits or reserve as another user.
REVOKE ALL ON FUNCTION public.reserve_paid_operation(uuid,text,integer,integer,integer,integer,uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.reserve_paid_operation(uuid,text,integer,integer,integer,integer,uuid) TO service_role;

COMMIT;
