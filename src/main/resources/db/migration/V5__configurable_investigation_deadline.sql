-- Preserve the first claim deadline across recovery and configuration changes.
DROP FUNCTION claim_investigation();
CREATE FUNCTION claim_investigation(budget_seconds integer DEFAULT 240) RETURNS TABLE(id uuid,requested_by uuid,lease_token uuid,deadline_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF budget_seconds<30 OR budget_seconds>600 OR budget_seconds IS NULL THEN RAISE EXCEPTION 'Invalid investigation deadline budget'; END IF;
 UPDATE investigation_jobs j SET state='PARTIAL',stage='STOPPED',error_code='RECOVERY_OR_BUDGET_EXHAUSTED'
 WHERE j.state='RUNNING' AND j.lease_until<now() AND (j.attempts>=3 OR j.deadline_at<=now());
 RETURN QUERY WITH candidate AS (
  SELECT j.id FROM investigation_jobs j WHERE (j.state='QUEUED' OR (j.state='RUNNING' AND j.lease_until<now()))
  AND j.attempts<3 AND (j.deadline_at IS NULL OR j.deadline_at>now()) ORDER BY j.created_at FOR UPDATE SKIP LOCKED LIMIT 1
 ) UPDATE investigation_jobs j SET state='RUNNING',stage='EXTRACTING',attempts=j.attempts+1,lease_token=gen_random_uuid(),
 deadline_at=coalesce(j.deadline_at,now()+make_interval(secs=>budget_seconds)),
 lease_until=least(now()+interval '3 minutes',coalesce(j.deadline_at,now()+make_interval(secs=>budget_seconds)))
 FROM candidate c WHERE j.id=c.id RETURNING j.id,j.requested_by,j.lease_token,j.deadline_at;
END $$;
REVOKE EXECUTE ON FUNCTION claim_investigation(integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION claim_investigation(integer) TO investigator_runtime;
