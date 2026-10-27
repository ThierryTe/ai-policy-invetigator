-- Expose authorized ingestion progress through version history, including after a client reload.
CREATE FUNCTION version_job(version uuid)
RETURNS TABLE(job_id uuid,job_status text,stage text,error_code text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT j.id,j.status,j.stage,j.error_code
 FROM ingestion_tasks j JOIN policy_versions v ON v.id=j.version_id
 WHERE v.id=version
$$;
REVOKE EXECUTE ON FUNCTION version_job(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION version_job(uuid) TO investigator_runtime;
