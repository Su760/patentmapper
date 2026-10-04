BEGIN;

CREATE TABLE public.analysis_queue (
  search_id uuid PRIMARY KEY REFERENCES public.searches(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  submission_key uuid NOT NULL,
  payload jsonb NOT NULL,
  execution_inputs jsonb NOT NULL,
  state text NOT NULL CHECK (state IN ('queued','running','finalizing','finished','failed','interrupted')),
  result_snapshot jsonb,
  lease_token uuid,
  lease_expires_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  last_claimed_at timestamptz,
  UNIQUE(user_id,submission_key)
);
CREATE INDEX analysis_queue_claim_idx ON public.analysis_queue(state,created_at);
ALTER TABLE public.analysis_queue ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.analysis_queue FROM PUBLIC,anon,authenticated,service_role;
GRANT SELECT ON public.analysis_queue TO service_role;
ALTER TABLE public.searches ADD COLUMN lease_expires_at timestamptz;

-- No paid replay or ownership adoption of legacy in-process work.
UPDATE public.searches SET status='interrupted',current_step='interrupted',
  error_message='Legacy execution was interrupted. Start a fresh analysis to continue; it consumes new usage.'
  WHERE status='processing' AND user_id IS NOT NULL;

CREATE FUNCTION public.admit_analysis(p_user_id uuid,p_submission_key uuid,p_payload jsonb,
  p_execution_inputs jsonb,p_free_limit integer,p_pro_limit integer,p_global_limit integer,p_window_seconds integer)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE existing public.analysis_queue; job_id uuid; outcome text;
BEGIN
  IF p_user_id IS NULL OR p_submission_key IS NULL
    OR jsonb_typeof(p_payload) IS DISTINCT FROM 'object'
    OR btrim(coalesce(p_payload->>'invention_idea',''))=''
    OR coalesce(p_payload->>'jurisdiction','') NOT IN ('all','us','ep','wo')
    OR jsonb_typeof(p_execution_inputs) IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'Invalid admission inputs';
  END IF;
  -- Same lock as the quota ledger; lookup, reservation and insertion commit together.
  PERFORM pg_advisory_xact_lock(726183940221::bigint);
  SELECT * INTO existing FROM public.analysis_queue q
    WHERE q.user_id=p_user_id AND q.submission_key=p_submission_key;
  IF FOUND THEN
    IF existing.payload<>p_payload THEN RETURN jsonb_build_object('outcome','conflict'); END IF;
    RETURN jsonb_build_object('outcome','accepted','job_id',existing.search_id,
      'status',(SELECT status FROM public.searches WHERE id=existing.search_id));
  END IF;
  job_id := gen_random_uuid();
  outcome := public.reserve_paid_operation(p_user_id,'job',p_free_limit,p_pro_limit,p_global_limit,p_window_seconds,job_id);
  IF outcome<>'allowed' THEN RETURN jsonb_build_object('outcome',outcome); END IF;
  INSERT INTO public.searches(id,user_id,invention_idea,status,current_step)
    VALUES(job_id,p_user_id,p_payload->>'invention_idea','queued','queued');
  INSERT INTO public.analysis_queue(search_id,user_id,submission_key,payload,execution_inputs,state)
    VALUES(job_id,p_user_id,p_submission_key,p_payload,p_execution_inputs,'queued');
  RETURN jsonb_build_object('outcome','accepted','job_id',job_id,'status','queued');
END $$;

CREATE FUNCTION public.claim_analysis(p_lease_seconds integer,p_max_active integer)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE job public.analysis_queue;
BEGIN
  IF p_lease_seconds IS NULL OR p_lease_seconds<1 OR p_max_active IS NULL OR p_max_active<1 THEN
    RAISE EXCEPTION 'Invalid worker limits';
  END IF;
  PERFORM pg_advisory_xact_lock(726183940222::bigint);
  -- Lock before checking the clock, so a concurrent heartbeat cannot be overwritten.
  FOR job IN SELECT * FROM public.analysis_queue WHERE state='running' FOR UPDATE LOOP
    IF job.lease_expires_at<=clock_timestamp() THEN
      UPDATE public.analysis_queue SET state='interrupted',lease_expires_at=NULL WHERE search_id=job.search_id;
      UPDATE public.searches SET status='interrupted',current_step='interrupted',lease_expires_at=NULL,
        error_message='Execution was interrupted. Paid calls may have occurred; usage is retained. Start a fresh paid analysis to continue.' WHERE id=job.search_id;
    END IF;
  END LOOP;
  IF (SELECT count(*) FROM public.analysis_queue WHERE state IN ('running','finalizing')
      AND lease_expires_at>clock_timestamp())>=p_max_active THEN RETURN NULL; END IF;
  SELECT * INTO job FROM public.analysis_queue
    WHERE state='queued' OR (state='finalizing' AND lease_expires_at<=clock_timestamp())
    ORDER BY coalesce(last_claimed_at,created_at),search_id FOR UPDATE SKIP LOCKED LIMIT 1;
  IF NOT FOUND THEN RETURN NULL; END IF;
  UPDATE public.analysis_queue SET state=CASE WHEN state='queued' THEN 'running' ELSE state END,
    last_claimed_at=clock_timestamp(),lease_token=gen_random_uuid(),lease_expires_at=clock_timestamp()+make_interval(secs=>p_lease_seconds)
    WHERE search_id=job.search_id RETURNING * INTO job;
  UPDATE public.searches SET status=job.state,current_step=CASE WHEN job.state='running' THEN 'starting' ELSE 'finalizing' END,
    lease_expires_at=job.lease_expires_at WHERE id=job.search_id;
  RETURN to_jsonb(job);
END $$;

-- Status reads may expose expiry even when every worker is offline. No admission.
CREATE FUNCTION public.read_analysis_status(p_search_id uuid,p_user_id uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE job public.analysis_queue;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM public.searches WHERE id=p_search_id AND user_id=p_user_id) THEN RETURN NULL; END IF;
  SELECT * INTO job FROM public.analysis_queue WHERE search_id=p_search_id FOR UPDATE;
  IF job.state='running' AND job.lease_expires_at<=clock_timestamp() THEN
    UPDATE public.analysis_queue SET state='interrupted',lease_expires_at=NULL WHERE search_id=p_search_id;
    UPDATE public.searches SET status='interrupted',current_step='interrupted',lease_expires_at=NULL,
      error_message='Execution was interrupted. Paid calls may have occurred; usage is retained. Start a fresh paid analysis to continue.' WHERE id=p_search_id;
  END IF;
  RETURN (SELECT to_jsonb(s) FROM public.searches s WHERE id=p_search_id AND user_id=p_user_id);
END $$;

-- This helper locks the queue row and checks expiry AFTER acquiring the lock.
CREATE FUNCTION public.analysis_lease_valid(p_search_id uuid,p_token uuid)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE job public.analysis_queue;
BEGIN
  SELECT * INTO job FROM public.analysis_queue WHERE search_id=p_search_id FOR UPDATE;
  RETURN coalesce(job.lease_token=p_token AND job.state IN ('running','finalizing')
    AND job.lease_expires_at>clock_timestamp(),false);
END $$;

CREATE FUNCTION public.heartbeat_analysis(p_search_id uuid,p_token uuid,p_lease_seconds integer)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN
  IF p_lease_seconds IS NULL OR p_lease_seconds<1 THEN RAISE EXCEPTION 'Invalid lease'; END IF;
  IF NOT public.analysis_lease_valid(p_search_id,p_token) THEN RETURN false; END IF;
  UPDATE public.analysis_queue SET lease_expires_at=clock_timestamp()+make_interval(secs=>p_lease_seconds) WHERE search_id=p_search_id;
  UPDATE public.searches SET lease_expires_at=(SELECT lease_expires_at FROM public.analysis_queue WHERE search_id=p_search_id) WHERE id=p_search_id;
  RETURN true;
END $$;

CREATE FUNCTION public.stage_analysis(p_search_id uuid,p_token uuid,p_step text)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN
  IF NOT public.analysis_lease_valid(p_search_id,p_token) OR
     (SELECT state FROM public.analysis_queue WHERE search_id=p_search_id)<>'running' THEN RETURN false; END IF;
  UPDATE public.searches SET current_step=p_step WHERE id=p_search_id;
  RETURN true;
END $$;

CREATE FUNCTION public.validate_analysis_output(p_result jsonb,p_patents jsonb)
RETURNS void LANGUAGE plpgsql SET search_path='' AS $$
DECLARE outcome text;
BEGIN
  outcome := p_result->>'retrieval_outcome';
  IF outcome IS NULL OR outcome NOT IN ('complete','partial','insufficient_evidence')
     OR jsonb_typeof(p_result->'clusters') IS DISTINCT FROM 'array'
     OR jsonb_typeof(p_result->'citation_links') IS DISTINCT FROM 'array'
     OR jsonb_typeof(p_result->'coverage_warnings') IS DISTINCT FROM 'array'
     OR jsonb_typeof(p_patents) IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'Invalid finalization payload';
  END IF;
  IF outcome='insufficient_evidence' THEN
    IF jsonb_array_length(p_patents)<>0 OR p_result->'clusters'<>'[]'::jsonb
       OR p_result->'citation_links'<>'[]'::jsonb
       OR coalesce(p_result->>'final_report','')<>''
       OR coalesce(p_result->>'white_space_analysis','')<>'' THEN
      RAISE EXCEPTION 'Insufficient evidence cannot contain conclusions';
    END IF;
  ELSE
    IF jsonb_array_length(p_patents)=0 OR btrim(coalesce(p_result->>'final_report',''))='' THEN
      RAISE EXCEPTION 'Completed analysis requires evidence and a report';
    END IF;
  END IF;
  IF EXISTS (SELECT 1 FROM jsonb_array_elements(p_patents) p
      WHERE jsonb_typeof(p) IS DISTINCT FROM 'object'
         OR btrim(coalesce(p->>'patent_id',''))=''
         OR (btrim(coalesce(p->>'title',''))='' AND btrim(coalesce(p->>'abstract',''))='')) THEN
    RAISE EXCEPTION 'Unusable patent in finalization payload';
  END IF;

END $$;
REVOKE ALL ON FUNCTION public.validate_analysis_output(jsonb,jsonb) FROM PUBLIC,anon,authenticated,service_role;

CREATE FUNCTION public.checkpoint_analysis(p_search_id uuid,p_token uuid,p_output jsonb)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN
  IF NOT public.analysis_lease_valid(p_search_id,p_token) THEN RETURN false; END IF;
  IF (SELECT state FROM public.analysis_queue WHERE search_id=p_search_id)='finalizing' THEN
    RETURN (SELECT result_snapshot=p_output FROM public.analysis_queue WHERE search_id=p_search_id);
  END IF;
  IF jsonb_typeof(p_output->'result') IS DISTINCT FROM 'object' OR jsonb_typeof(p_output->'patents') IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'Invalid checkpoint';
  END IF;
  PERFORM public.validate_analysis_output(p_output->'result',p_output->'patents');
  UPDATE public.analysis_queue SET state='finalizing',result_snapshot=p_output WHERE search_id=p_search_id;
  UPDATE public.searches SET status='finalizing',current_step='finalizing' WHERE id=p_search_id;
  RETURN true;
END $$;

CREATE FUNCTION public.fail_analysis(p_search_id uuid,p_token uuid,p_error text)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN
  IF NOT public.analysis_lease_valid(p_search_id,p_token) OR
    (SELECT state FROM public.analysis_queue WHERE search_id=p_search_id)<>'running' THEN RETURN false; END IF;
  UPDATE public.analysis_queue SET state='failed',lease_expires_at=NULL WHERE search_id=p_search_id;
  UPDATE public.searches SET status='failed',current_step='failed',error_message=p_error,lease_expires_at=NULL WHERE id=p_search_id;
  RETURN true;
END $$;

-- Internal publication only; service callers must use the fenced wrapper.
CREATE OR REPLACE FUNCTION public.finalize_analysis(p_search_id uuid, p_result jsonb, p_patents jsonb)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
  job_status text;
  outcome text;
BEGIN
  SELECT s.status INTO job_status FROM public.searches s
    WHERE s.id=p_search_id AND s.user_id IS NOT NULL FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Owned search not found'; END IF;
  -- A retry after commit (including a lost response) cannot replace saved data
  -- or erase claims generated since completion.
  IF job_status IN ('completed','insufficient_evidence') THEN RETURN 'already_finalized'; END IF;
  IF job_status <> 'finalizing' THEN RAISE EXCEPTION 'Invalid search status'; END IF;

  PERFORM public.validate_analysis_output(p_result,p_patents);
  outcome := p_result->>'retrieval_outcome';
  INSERT INTO public.search_results(search_id,clusters,white_space_analysis,final_report,citation_links,retrieval_outcome,coverage_warnings)
    VALUES(p_search_id,p_result->'clusters',p_result->>'white_space_analysis',
      CASE WHEN outcome='insufficient_evidence' THEN NULL ELSE p_result->>'final_report' END,
      p_result->'citation_links',outcome,p_result->'coverage_warnings')
    ON CONFLICT(search_id) DO UPDATE SET clusters=EXCLUDED.clusters,
      white_space_analysis=EXCLUDED.white_space_analysis, final_report=EXCLUDED.final_report,
      citation_links=EXCLUDED.citation_links, retrieval_outcome=EXCLUDED.retrieval_outcome,
      coverage_warnings=EXCLUDED.coverage_warnings;
  -- Replace any legacy partial writes within this transaction. Use an allowlist
  -- and the trusted search ID, never IDs from provider JSON. Preserve first match.
  DELETE FROM public.patents WHERE search_id=p_search_id;
  INSERT INTO public.patents(search_id,patent_id,title,abstract,assignee,url)
    SELECT DISTINCT ON (btrim(p->>'patent_id')) p_search_id,btrim(p->>'patent_id'),
      p->>'title',p->>'abstract',p->>'assignee',p->>'url'
    FROM jsonb_array_elements(p_patents) WITH ORDINALITY AS items(p,ordinal)
    ORDER BY btrim(p->>'patent_id'),ordinal;
  UPDATE public.searches SET
    status=CASE WHEN outcome='insufficient_evidence' THEN 'insufficient_evidence' ELSE 'completed' END,
    current_step='done', error_message=NULL WHERE id=p_search_id;
  RETURN 'saved';
END $$;
REVOKE ALL ON FUNCTION public.finalize_analysis(uuid,jsonb,jsonb) FROM PUBLIC,anon,authenticated,service_role;

CREATE FUNCTION public.publish_analysis(p_search_id uuid,p_token uuid)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE job public.analysis_queue;
BEGIN
  SELECT * INTO job FROM public.analysis_queue WHERE search_id=p_search_id FOR UPDATE;
  IF job.lease_token IS DISTINCT FROM p_token OR p_token IS NULL THEN RETURN false; END IF;
  IF job.state='finished' THEN RETURN true; END IF;
  IF NOT public.analysis_lease_valid(p_search_id,p_token) OR job.state<>'finalizing' THEN RETURN false; END IF;
  PERFORM public.finalize_analysis(p_search_id,job.result_snapshot->'result',job.result_snapshot->'patents');
  -- A slow transaction cannot publish after its lease has expired.
  IF NOT public.analysis_lease_valid(p_search_id,p_token) THEN RAISE EXCEPTION 'Lease expired during publication'; END IF;
  UPDATE public.analysis_queue SET state='finished',lease_expires_at=NULL WHERE search_id=p_search_id;
  UPDATE public.searches SET lease_expires_at=NULL WHERE id=p_search_id;
  RETURN true;
END $$;

REVOKE TRUNCATE ON public.searches,public.search_results,public.patents FROM service_role;

-- Prevent old service-role clients from bypassing fenced status/publication RPCs.
-- Claims cache remains an independently authorized, metered operation.
CREATE FUNCTION public.guard_durable_analysis_write() RETURNS trigger
LANGUAGE plpgsql SET search_path='' AS $$
DECLARE job_id uuid;
BEGIN
  IF current_user<>'service_role' THEN
    IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
  END IF;
  IF TG_OP='DELETE' THEN
    IF TG_TABLE_NAME='searches' THEN job_id:=OLD.id; ELSE job_id:=OLD.search_id; END IF;
    IF EXISTS (SELECT 1 FROM public.analysis_queue WHERE search_id=job_id) THEN RAISE EXCEPTION 'Durable analysis writes must be fenced'; END IF;
    RETURN OLD;
  END IF;
  IF TG_TABLE_NAME='searches' THEN job_id:=NEW.id; ELSE job_id:=NEW.search_id; END IF;
  IF TG_OP='UPDATE' AND TG_TABLE_NAME<>'searches' THEN
    IF OLD.search_id IS DISTINCT FROM NEW.search_id AND EXISTS (SELECT 1 FROM public.analysis_queue WHERE search_id=OLD.search_id) THEN
      RAISE EXCEPTION 'Durable analysis writes must be fenced';
    END IF;
  END IF;
  IF EXISTS (SELECT 1 FROM public.analysis_queue WHERE search_id=job_id) THEN
    IF TG_TABLE_NAME='search_results' AND TG_OP='UPDATE' THEN
      IF (to_jsonb(NEW)-'claims_analysis')=(to_jsonb(OLD)-'claims_analysis') THEN RETURN NEW; END IF;
    END IF;
    RAISE EXCEPTION 'Durable analysis writes must be fenced';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER durable_search_guard BEFORE INSERT OR UPDATE OR DELETE ON public.searches FOR EACH ROW EXECUTE FUNCTION public.guard_durable_analysis_write();
CREATE TRIGGER durable_result_guard BEFORE INSERT OR UPDATE OR DELETE ON public.search_results FOR EACH ROW EXECUTE FUNCTION public.guard_durable_analysis_write();
CREATE TRIGGER durable_patent_guard BEFORE INSERT OR UPDATE OR DELETE ON public.patents FOR EACH ROW EXECUTE FUNCTION public.guard_durable_analysis_write();

REVOKE ALL ON FUNCTION public.analysis_lease_valid(uuid,uuid),public.guard_durable_analysis_write() FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.admit_analysis(uuid,uuid,jsonb,jsonb,integer,integer,integer,integer),
  public.read_analysis_status(uuid,uuid),public.claim_analysis(integer,integer),public.heartbeat_analysis(uuid,uuid,integer),public.stage_analysis(uuid,uuid,text),
  public.checkpoint_analysis(uuid,uuid,jsonb),public.fail_analysis(uuid,uuid,text),public.publish_analysis(uuid,uuid)
  FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.admit_analysis(uuid,uuid,jsonb,jsonb,integer,integer,integer,integer),
  public.read_analysis_status(uuid,uuid),public.claim_analysis(integer,integer),public.heartbeat_analysis(uuid,uuid,integer),public.stage_analysis(uuid,uuid,text),
  public.checkpoint_analysis(uuid,uuid,jsonb),public.fail_analysis(uuid,uuid,text),public.publish_analysis(uuid,uuid)
  TO service_role;
NOTIFY pgrst,'reload schema';
COMMIT;
