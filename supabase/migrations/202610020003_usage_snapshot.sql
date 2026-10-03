BEGIN;

-- One definition for admission AND display. Never browser callable: the backend
-- supplies the validated user and configured window, not client-chosen values.
CREATE OR REPLACE FUNCTION public.paid_usage_snapshot(p_user_id uuid, p_window_seconds integer)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
  as_of timestamptz := clock_timestamp();
  window_start timestamptz;
  anonymous_user boolean;
  plan text := 'free';
  snapshot jsonb;
BEGIN
  IF p_user_id IS NULL OR p_window_seconds IS NULL OR p_window_seconds <= 0 THEN
    RAISE EXCEPTION 'Invalid usage snapshot parameters';
  END IF;
  window_start := as_of - make_interval(secs => p_window_seconds);
  SELECT u.is_anonymous INTO anonymous_user FROM auth.users u WHERE u.id=p_user_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'Unknown usage owner'; END IF;
  IF NOT anonymous_user AND EXISTS (
    SELECT 1 FROM public.subscriptions s WHERE s.user_id=p_user_id AND s.plan='pro' AND s.status='active'
      AND (s.current_period_end IS NULL OR s.current_period_end > as_of)
  ) THEN plan := 'pro'; END IF;
  SELECT jsonb_build_object(
    'plan', plan, 'as_of', as_of, 'window_seconds', p_window_seconds,
    'used', jsonb_build_object(
      'job', count(*) FILTER (WHERE r.user_id=p_user_id AND r.operation='job'),
      'claims', count(*) FILTER (WHERE r.user_id=p_user_id AND r.operation='claims'),
      'ideation', count(*) FILTER (WHERE r.user_id=p_user_id AND r.operation='ideation')),
    'global_used', count(*)
  ) INTO snapshot FROM public.usage_reservations r WHERE r.created_at>=window_start;
  RETURN snapshot;
END $$;
REVOKE ALL ON FUNCTION public.paid_usage_snapshot(uuid,integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.paid_usage_snapshot(uuid,integer) TO service_role;

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
  snapshot jsonb;
  user_limit integer;
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
  snapshot := public.paid_usage_snapshot(p_user_id, p_window_seconds);
  user_limit := CASE WHEN snapshot->>'plan' = 'pro' THEN p_pro_limit ELSE p_free_limit END;
  IF (snapshot->'used'->>p_operation)::bigint >= user_limit THEN
    RETURN 'user_limit';
  END IF;
  IF (snapshot->>'global_used')::bigint >= p_global_limit THEN
    RETURN 'global_limit';
  END IF;
  INSERT INTO public.usage_reservations(user_id,operation,linked_search_id,created_at)
    VALUES (p_user_id,p_operation,p_search_id,clock_timestamp());
  RETURN 'allowed';
END $$;

REVOKE ALL ON FUNCTION public.reserve_paid_operation(uuid,text,integer,integer,integer,integer,uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.reserve_paid_operation(uuid,text,integer,integer,integer,integer,uuid) TO service_role;
COMMIT;
