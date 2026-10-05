BEGIN;
-- Coordinated forward rollout: stop API/workers before applying. No paid replay.
ALTER TABLE public.patents ADD COLUMN evidence jsonb;
ALTER TABLE public.search_results ADD COLUMN evidence_version integer;
ALTER TABLE public.search_results ADD COLUMN requested_jurisdiction text;
ALTER TABLE public.search_results ADD COLUMN analysis_warnings jsonb NOT NULL DEFAULT '[]';

-- Queued v1 has never executed; explicitly migrate its execution contract to v2.
UPDATE public.analysis_queue SET execution_inputs=execution_inputs || '{"version":2,"upgraded_from_version":1}'::jsonb
  WHERE state='queued' AND execution_inputs->>'version'='1';
-- A running v1 cannot be safely replayed or resume under changed semantics.
UPDATE public.searches SET status='interrupted',current_step='interrupted',lease_expires_at=NULL,
  error_message='Execution interrupted by evidence upgrade. Usage is retained; a fresh analysis consumes new usage.'
  WHERE id IN (SELECT search_id FROM public.analysis_queue WHERE state='running' AND execution_inputs->>'version'='1');
UPDATE public.analysis_queue SET state='interrupted',lease_expires_at=NULL
  WHERE state='running' AND execution_inputs->>'version'='1';
-- Finalizing v1 snapshots and historical result rows are untouched. Missing stays NULL.

CREATE OR REPLACE FUNCTION public.validate_analysis_output(p_result jsonb,p_patents jsonb)
RETURNS void LANGUAGE plpgsql SET search_path='' AS $$
DECLARE outcome text; evidence_patent jsonb; o jsonb;
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

  IF p_result->>'evidence_version' IS NOT NULL THEN
    IF p_result->'evidence_version' <> '1'::jsonb
      OR jsonb_typeof(p_result->'analysis_warnings') IS DISTINCT FROM 'array'
      OR coalesce(p_result->>'requested_jurisdiction','') NOT IN ('all','us','ep','wo') THEN
      RAISE EXCEPTION 'Invalid evidence result version or metadata';
    END IF;
    IF (SELECT count(*) FROM jsonb_array_elements(p_patents)) <>
       (SELECT count(DISTINCT p->>'patent_id') FROM jsonb_array_elements(p_patents) p) THEN
      RAISE EXCEPTION 'Duplicate evidence identities';
    END IF;
    FOR evidence_patent IN SELECT value FROM jsonb_array_elements(p_patents) LOOP
      IF jsonb_typeof(evidence_patent->'evidence') IS DISTINCT FROM 'object'
        OR evidence_patent->'evidence'->'version' IS DISTINCT FROM '1'::jsonb
        OR jsonb_typeof(evidence_patent->'evidence'->'observations') IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'Invalid evidence version or observations';
      END IF;
      IF jsonb_array_length(evidence_patent->'evidence'->'observations')=0 THEN RAISE EXCEPTION 'Empty evidence observations'; END IF;
      FOR o IN SELECT value FROM jsonb_array_elements(evidence_patent->'evidence'->'observations') LOOP
        IF jsonb_typeof(o) IS DISTINCT FROM 'object'
          OR NOT (o ?& ARRAY['provider','provider_record_id','publication_id','source_url','retrieved_at','matching_queries','text','text_type','language','dates','requested_jurisdiction','jurisdiction_filter','coverage_limitations'])
          OR coalesce(o->>'provider','') NOT IN ('lens','serpapi','synthetic')
          OR btrim(coalesce(o->>'provider_record_id',''))=''
          OR evidence_patent->>'patent_id' IS DISTINCT FROM (o->>'provider') || ':' || (o->>'provider_record_id')
          OR jsonb_typeof(o->'text') IS DISTINCT FROM 'string'
          OR btrim(o->>'text')=''
          OR coalesce(o->>'text_type','') NOT IN ('abstract','search_snippet','title_only','synthetic')
          OR ((o->>'provider'='synthetic') IS DISTINCT FROM (o->>'text_type'='synthetic'))
          OR jsonb_typeof(o->'matching_queries') IS DISTINCT FROM 'array'
          OR jsonb_typeof(o->'coverage_limitations') IS DISTINCT FROM 'array'
          OR jsonb_typeof(o->'dates') IS DISTINCT FROM 'object'
          OR NOT ((o->'dates') ?& ARRAY['priority','filing','publication'])
          OR btrim(coalesce(o->>'retrieved_at',''))=''
          OR o->>'requested_jurisdiction' IS DISTINCT FROM p_result->>'requested_jurisdiction' THEN
          RAISE EXCEPTION 'Invalid evidence observation';
        END IF;
      END LOOP;
    END LOOP;
    IF EXISTS (SELECT 1 FROM jsonb_array_elements(p_result->'clusters') c,
      jsonb_array_elements_text(c->'patent_ids') id WHERE NOT EXISTS
      (SELECT 1 FROM jsonb_array_elements(p_patents) p WHERE p->>'patent_id'=id))
      OR EXISTS (SELECT 1 FROM jsonb_array_elements(p_result->'citation_links') l WHERE
        NOT EXISTS (SELECT 1 FROM jsonb_array_elements(p_patents) p WHERE p->>'patent_id'=l->>'source')
        OR NOT EXISTS (SELECT 1 FROM jsonb_array_elements(p_patents) p WHERE p->>'patent_id'=l->>'target')
        OR l->'is_ai_inferred' IS DISTINCT FROM 'true'::jsonb) THEN
      RAISE EXCEPTION 'Unknown evidence reference';
    END IF;
  END IF;

END $$;
CREATE OR REPLACE FUNCTION public.checkpoint_analysis(p_search_id uuid,p_token uuid,p_output jsonb)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN
  IF NOT public.analysis_lease_valid(p_search_id,p_token) THEN RETURN false; END IF;
  IF (SELECT state FROM public.analysis_queue WHERE search_id=p_search_id)='finalizing' THEN
    RETURN (SELECT result_snapshot=p_output FROM public.analysis_queue WHERE search_id=p_search_id);
  END IF;
  IF jsonb_typeof(p_output->'result') IS DISTINCT FROM 'object' OR jsonb_typeof(p_output->'patents') IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'Invalid checkpoint';
  END IF;
  IF (SELECT execution_inputs->>'version' FROM public.analysis_queue WHERE search_id=p_search_id)='2'
    AND p_output->'result'->'evidence_version' IS DISTINCT FROM '1'::jsonb THEN
    RAISE EXCEPTION 'Version 2 execution requires evidence v1';
  END IF;
  PERFORM public.validate_analysis_output(p_output->'result',p_output->'patents');
  UPDATE public.analysis_queue SET state='finalizing',result_snapshot=p_output WHERE search_id=p_search_id;
  UPDATE public.searches SET status='finalizing',current_step='finalizing' WHERE id=p_search_id;
  RETURN true;
END $$;

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
  INSERT INTO public.search_results(search_id,clusters,white_space_analysis,final_report,citation_links,retrieval_outcome,coverage_warnings,evidence_version,requested_jurisdiction,analysis_warnings)
    VALUES(p_search_id,p_result->'clusters',p_result->>'white_space_analysis',
      CASE WHEN outcome='insufficient_evidence' THEN NULL ELSE p_result->>'final_report' END,
      p_result->'citation_links',outcome,p_result->'coverage_warnings',
      (p_result->>'evidence_version')::integer,p_result->>'requested_jurisdiction',coalesce(p_result->'analysis_warnings','[]'))
    ON CONFLICT(search_id) DO UPDATE SET clusters=EXCLUDED.clusters,
      white_space_analysis=EXCLUDED.white_space_analysis, final_report=EXCLUDED.final_report,
      citation_links=EXCLUDED.citation_links, retrieval_outcome=EXCLUDED.retrieval_outcome,
      coverage_warnings=EXCLUDED.coverage_warnings,evidence_version=EXCLUDED.evidence_version,
      requested_jurisdiction=EXCLUDED.requested_jurisdiction,analysis_warnings=EXCLUDED.analysis_warnings;
  -- Replace any legacy partial writes within this transaction. Use an allowlist
  -- and the trusted search ID, never IDs from provider JSON. Preserve first match.
  DELETE FROM public.patents WHERE search_id=p_search_id;
  INSERT INTO public.patents(search_id,patent_id,title,abstract,assignee,url,evidence)
    SELECT DISTINCT ON (btrim(p->>'patent_id')) p_search_id,btrim(p->>'patent_id'),
      p->>'title',p->>'abstract',p->>'assignee',p->>'url',
      CASE WHEN p_result->>'evidence_version'='1' THEN p->'evidence' ELSE NULL END
    FROM jsonb_array_elements(p_patents) WITH ORDINALITY AS items(p,ordinal)
    ORDER BY btrim(p->>'patent_id'),ordinal;
  UPDATE public.searches SET
    status=CASE WHEN outcome='insufficient_evidence' THEN 'insufficient_evidence' ELSE 'completed' END,
    current_step='done', error_message=NULL WHERE id=p_search_id;
  RETURN 'saved';
END $$;
REVOKE ALL ON FUNCTION public.finalize_analysis(uuid,jsonb,jsonb) FROM PUBLIC,anon,authenticated,service_role;


NOTIFY pgrst,'reload schema';
COMMIT;
