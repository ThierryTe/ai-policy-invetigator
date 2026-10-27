CREATE TABLE investigations (
 id uuid PRIMARY KEY, requested_by uuid NOT NULL REFERENCES app_users, request_key uuid NOT NULL, payload_digest text NOT NULL, UNIQUE(requested_by,request_key),
 baseline_id uuid NOT NULL REFERENCES policy_versions, replacement_id uuid NOT NULL REFERENCES policy_versions,
 procedure_ids uuid[] NOT NULL CHECK(cardinality(procedure_ids) BETWEEN 1 AND 4),
 analysis_date date NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), CHECK(baseline_id<>replacement_id)
);
CREATE FUNCTION investigation_readable(baseline uuid,replacement uuid,procedures uuid[]) RETURNS boolean
LANGUAGE sql STABLE AS $$
 SELECT (SELECT count(*) FROM policy_versions WHERE id=ANY(array[baseline,replacement]||procedures))=2+cardinality(procedures)
$$;
ALTER TABLE investigations ENABLE ROW LEVEL SECURITY;
ALTER TABLE investigations FORCE ROW LEVEL SECURITY;
CREATE POLICY investigation_read ON investigations FOR SELECT USING(investigation_readable(baseline_id,replacement_id,procedure_ids));
CREATE POLICY investigation_create ON investigations FOR INSERT WITH CHECK(requested_by=current_actor()
 AND investigation_readable(baseline_id,replacement_id,procedure_ids)
 AND EXISTS(SELECT 1 FROM policy_versions WHERE id=replacement_id AND can_write_policy(policy_id)));
CREATE TABLE requirement_extractions (
 investigation_id uuid NOT NULL REFERENCES investigations, version_id uuid NOT NULL REFERENCES policy_versions,
 payload jsonb NOT NULL, source_hash text NOT NULL, model text NOT NULL, prompt_version text NOT NULL, schema_version text NOT NULL,
 PRIMARY KEY(investigation_id,version_id)
);
CREATE TABLE investigation_assessments (
 id uuid PRIMARY KEY, investigation_id uuid NOT NULL UNIQUE REFERENCES investigations,
 payload jsonb NOT NULL, model text NOT NULL,prompt_version text NOT NULL,schema_version text NOT NULL
);
ALTER TABLE requirement_extractions ENABLE ROW LEVEL SECURITY;
ALTER TABLE requirement_extractions FORCE ROW LEVEL SECURITY;
CREATE POLICY extraction_read ON requirement_extractions FOR SELECT USING(EXISTS(SELECT 1 FROM investigations i WHERE i.id=investigation_id));
CREATE POLICY extraction_insert ON requirement_extractions FOR INSERT WITH CHECK(EXISTS(SELECT 1 FROM investigations i WHERE i.id=investigation_id AND i.requested_by=current_actor()));
ALTER TABLE investigation_assessments ENABLE ROW LEVEL SECURITY;
ALTER TABLE investigation_assessments FORCE ROW LEVEL SECURITY;
CREATE POLICY assessment_read ON investigation_assessments FOR SELECT USING(EXISTS(SELECT 1 FROM investigations i WHERE i.id=investigation_id));
CREATE POLICY assessment_insert ON investigation_assessments FOR INSERT WITH CHECK(EXISTS(SELECT 1 FROM investigations i WHERE i.id=investigation_id AND i.requested_by=current_actor()));
CREATE TABLE investigation_jobs (
 id uuid PRIMARY KEY REFERENCES investigations, requested_by uuid NOT NULL REFERENCES app_users,
 state text NOT NULL DEFAULT 'QUEUED' CHECK(state IN ('QUEUED','RUNNING','COMPLETED','PARTIAL','FAILED')),
 stage text NOT NULL DEFAULT 'QUEUED', error_code text, attempts integer NOT NULL DEFAULT 0,
 lease_token uuid,lease_until timestamptz,deadline_at timestamptz,
 metered_calls integer NOT NULL DEFAULT 0,calls integer NOT NULL DEFAULT 0,prompt_tokens integer NOT NULL DEFAULT 0,completion_tokens integer NOT NULL DEFAULT 0,
 latency_ms bigint NOT NULL DEFAULT 0, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE FUNCTION investigation_runnable(inv uuid) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM investigations i WHERE i.id=inv
  AND i.requested_by=current_actor()
  AND EXISTS(SELECT 1 FROM policy_versions v WHERE v.id=i.replacement_id AND can_write_policy(v.policy_id))
  AND NOT EXISTS(SELECT 1 FROM policy_versions v JOIN policies p ON p.id=v.policy_id
   WHERE v.id=ANY(array[i.baseline_id,i.replacement_id]||i.procedure_ids) AND (NOT p.external_processing_allowed OR v.status<>'INDEXED')))
$$;
CREATE FUNCTION schedule_investigation(inv uuid) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF NOT investigation_runnable(inv) THEN RAISE EXCEPTION 'Denied' USING ERRCODE='42501'; END IF;
 INSERT INTO investigation_jobs(id,requested_by) VALUES(inv,current_actor());
END $$;
CREATE FUNCTION claim_investigation() RETURNS TABLE(id uuid,requested_by uuid,lease_token uuid,deadline_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 UPDATE investigation_jobs j SET state='PARTIAL',stage='STOPPED',error_code='RECOVERY_OR_BUDGET_EXHAUSTED'
 WHERE j.state='RUNNING' AND j.lease_until<now() AND (j.attempts>=3 OR j.deadline_at<=now());
 RETURN QUERY WITH candidate AS (
  SELECT j.id FROM investigation_jobs j WHERE (j.state='QUEUED' OR (j.state='RUNNING' AND j.lease_until<now()))
  AND j.attempts<3 AND (j.deadline_at IS NULL OR j.deadline_at>now()) ORDER BY j.created_at FOR UPDATE SKIP LOCKED LIMIT 1
 ) UPDATE investigation_jobs j SET state='RUNNING',stage='EXTRACTING',attempts=j.attempts+1,lease_token=gen_random_uuid(),
 deadline_at=coalesce(j.deadline_at,now()+interval '4 minutes'),
 lease_until=least(now()+interval '3 minutes',coalesce(j.deadline_at,now()+interval '4 minutes'))
 FROM candidate c WHERE j.id=c.id RETURNING j.id,j.requested_by,j.lease_token,j.deadline_at;
END $$;
CREATE FUNCTION reserve_investigation_call(inv uuid,lease uuid) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE affected integer;
BEGIN
 IF NOT investigation_runnable(inv) THEN RAISE EXCEPTION 'Denied' USING ERRCODE='42501'; END IF;
 UPDATE investigation_jobs SET calls=calls+1,lease_until=least(now()+interval '3 minutes',deadline_at)
 WHERE id=inv AND requested_by=current_actor() AND lease_token=lease AND state='RUNNING' AND lease_until>now()
 AND deadline_at>now() AND calls<20 AND prompt_tokens+completion_tokens<40000;
 GET DIAGNOSTICS affected=ROW_COUNT;RETURN affected=1;
END $$;
CREATE FUNCTION record_investigation_usage(inv uuid,lease uuid,prompt integer,completion integer,latency bigint) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE affected integer;
BEGIN
 IF prompt<0 OR completion<0 OR latency<0 THEN RAISE EXCEPTION 'Invalid usage';END IF;
 UPDATE investigation_jobs SET metered_calls=metered_calls+1,prompt_tokens=prompt_tokens+prompt,completion_tokens=completion_tokens+completion,latency_ms=latency_ms+latency
 WHERE id=inv AND lease_token=lease AND state='RUNNING';
 GET DIAGNOSTICS affected=ROW_COUNT;RETURN affected=1;
END $$;
CREATE FUNCTION finish_investigation(inv uuid,lease uuid,result text,code text) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE affected integer;
BEGIN
 IF result NOT IN ('COMPLETED','PARTIAL','FAILED') OR (code IS NOT NULL AND code !~ '^[A-Z_]{1,64}$') THEN RAISE EXCEPTION 'Invalid result';END IF;
 UPDATE investigation_jobs SET state=result,stage=CASE WHEN result='COMPLETED' THEN 'COMPLETED' ELSE 'STOPPED' END,error_code=code,lease_until=NULL
 WHERE id=inv AND lease_token=lease AND state='RUNNING' AND lease_until>now();
 GET DIAGNOSTICS affected=ROW_COUNT;RETURN affected=1;
END $$;
CREATE FUNCTION investigation_progress(inv uuid)
RETURNS TABLE(id uuid,state text,stage text,error_code text,attempts integer,calls integer,metered_calls integer,prompt_tokens integer,completion_tokens integer,latency_ms bigint)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT j.id,j.state,j.stage,j.error_code,j.attempts,j.calls,j.metered_calls,j.prompt_tokens,j.completion_tokens,j.latency_ms
 FROM investigation_jobs j JOIN investigations i ON i.id=j.id WHERE i.id=inv
$$;
REVOKE ALL ON investigations,requirement_extractions,investigation_assessments,investigation_jobs FROM PUBLIC;
GRANT SELECT,INSERT ON investigations,requirement_extractions,investigation_assessments TO investigator_runtime;
REVOKE EXECUTE ON FUNCTION investigation_readable(uuid,uuid,uuid[]),investigation_runnable(uuid),schedule_investigation(uuid),claim_investigation(),reserve_investigation_call(uuid,uuid),record_investigation_usage(uuid,uuid,integer,integer,bigint),finish_investigation(uuid,uuid,text,text),investigation_progress(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION investigation_readable(uuid,uuid,uuid[]),investigation_runnable(uuid),schedule_investigation(uuid),claim_investigation(),reserve_investigation_call(uuid,uuid),record_investigation_usage(uuid,uuid,integer,integer,bigint),finish_investigation(uuid,uuid,text,text),investigation_progress(uuid) TO investigator_runtime;
CREATE FUNCTION checkpoint_investigation(inv uuid,lease uuid,new_stage text) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE affected integer;
BEGIN
 IF new_stage NOT IN ('EXTRACTING','ASSESSING') OR NOT investigation_runnable(inv) THEN RETURN false;END IF;
 UPDATE investigation_jobs SET stage=new_stage,lease_until=least(now()+interval '3 minutes',deadline_at)
 WHERE id=inv AND lease_token=lease AND state='RUNNING' AND lease_until>now() AND deadline_at>now();
 GET DIAGNOSTICS affected=ROW_COUNT;RETURN affected=1;
END $$;
REVOKE EXECUTE ON FUNCTION checkpoint_investigation(uuid,uuid,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION checkpoint_investigation(uuid,uuid,text) TO investigator_runtime;
