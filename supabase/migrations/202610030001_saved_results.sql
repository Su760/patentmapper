BEGIN;

-- NULL means no report was saved; never backfill it with gap analysis.
ALTER TABLE public.search_results ADD COLUMN IF NOT EXISTS final_report text;
ALTER TABLE public.search_results ADD COLUMN IF NOT EXISTS retrieval_outcome text;
ALTER TABLE public.search_results ADD COLUMN IF NOT EXISTS coverage_warnings jsonb NOT NULL DEFAULT '[]'::jsonb;

-- Backend-only publication transaction. Existing owner-read RLS remains in force.
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
  IF job_status NOT IN ('processing','failed') THEN RAISE EXCEPTION 'Invalid search status'; END IF;

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
REVOKE ALL ON FUNCTION public.finalize_analysis(uuid,jsonb,jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.finalize_analysis(uuid,jsonb,jsonb) TO service_role;

COMMIT;
