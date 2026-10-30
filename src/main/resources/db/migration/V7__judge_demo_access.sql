-- Operator-managed control plane. No runtime table access, role changes or content RLS bypass.
CREATE TABLE demo_meta_budget (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 max_attempts bigint NOT NULL DEFAULT 0 CHECK(max_attempts>=0),
 attempts bigint NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND max_attempts)
);
INSERT INTO demo_meta_budget(singleton) VALUES(true);

CREATE TABLE demo_access (
 user_id uuid PRIMARY KEY REFERENCES app_users,
 department_id uuid NOT NULL UNIQUE REFERENCES departments,
 expires_at timestamptz NOT NULL,
 max_imports integer NOT NULL CHECK(max_imports>=0),
 max_bytes bigint NOT NULL CHECK(max_bytes>=0),
 max_investigations integer NOT NULL CHECK(max_investigations>=0),
 max_pending integer NOT NULL CHECK(max_pending>0),
 max_meta_attempts bigint NOT NULL CHECK(max_meta_attempts>=0),
 imports integer NOT NULL DEFAULT 0 CHECK(imports BETWEEN 0 AND max_imports),
 bytes bigint NOT NULL DEFAULT 0 CHECK(bytes BETWEEN 0 AND max_bytes),
 investigations integer NOT NULL DEFAULT 0 CHECK(investigations BETWEEN 0 AND max_investigations),
 meta_attempts bigint NOT NULL DEFAULT 0 CHECK(meta_attempts BETWEEN 0 AND max_meta_attempts)
);
REVOKE ALL ON demo_access,demo_meta_budget FROM PUBLIC,investigator_runtime;
CREATE INDEX ingestion_pending_actor_idx ON ingestion_tasks(requested_by) WHERE status IN ('QUEUED','RUNNING');
CREATE INDEX investigation_pending_actor_idx ON investigation_jobs(requested_by) WHERE state IN ('QUEUED','RUNNING');

CREATE OR REPLACE FUNCTION active_identity(actor uuid) RETURNS TABLE(id uuid,organization_id uuid,email text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT u.id,u.organization_id,u.email FROM app_users u LEFT JOIN demo_access a ON a.user_id=u.id
 WHERE u.id=actor AND u.active AND (a.user_id IS NULL OR a.expires_at>statement_timestamp())
$$;
CREATE OR REPLACE FUNCTION login_identity(address text) RETURNS TABLE(id uuid,password_hash text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT u.id,u.password_hash FROM app_users u
 WHERE u.email=address AND EXISTS(SELECT 1 FROM active_identity(u.id))
$$;
CREATE OR REPLACE FUNCTION actor_memberships(actor uuid) RETURNS TABLE(department_id uuid,department_name text,role text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT m.department_id,d.name,m.role FROM memberships m JOIN active_identity(actor) u ON u.id=m.user_id
 JOIN departments d ON d.id=m.department_id LEFT JOIN demo_access a ON a.user_id=u.id
 WHERE d.organization_id=u.organization_id AND (a.user_id IS NULL OR m.department_id=a.department_id)
$$;
CREATE OR REPLACE FUNCTION can_access_policy(org uuid, dept uuid, policy uuid, writing boolean)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT EXISTS (
  SELECT 1 FROM active_identity(current_actor()) u JOIN memberships m ON m.user_id=u.id
  JOIN departments d ON d.id=m.department_id LEFT JOIN demo_access a ON a.user_id=u.id
  WHERE u.organization_id=org AND d.organization_id=org
   AND (a.user_id IS NULL OR (m.department_id=a.department_id AND (NOT writing OR dept=a.department_id)))
   AND (NOT writing OR m.role IN ('ANALYST','ADMIN'))
   AND (m.department_id=dept OR EXISTS (
    SELECT 1 FROM policy_grants g WHERE g.policy_id=policy AND g.department_id=m.department_id
      AND (NOT writing OR g.permission='WRITE')))
 )
$$;

-- Called only inside the existing admission transactions. Serialize different request keys too.
-- Lifetime counters are never refunded: failed ingestion/investigation still consumed resources.
CREATE FUNCTION reserve_demo_work(work text, pdf_bytes bigint) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE a demo_access%ROWTYPE; pending bigint;
BEGIN
 SELECT * INTO a FROM demo_access WHERE user_id=current_actor() FOR UPDATE;
 IF NOT FOUND THEN RETURN; END IF;
 IF a.expires_at<=clock_timestamp() THEN RAISE EXCEPTION 'DEMO_ACCESS_EXPIRED' USING ERRCODE='P7507'; END IF;
 SELECT (SELECT count(*) FROM ingestion_tasks WHERE requested_by=a.user_id AND status IN ('QUEUED','RUNNING'))
      + (SELECT count(*) FROM investigation_jobs WHERE requested_by=a.user_id AND state IN ('QUEUED','RUNNING')) INTO pending;
 IF pending>=a.max_pending THEN RAISE EXCEPTION 'DEMO_PENDING_LIMIT' USING ERRCODE='P7504'; END IF;
 IF work='IMPORT' AND pdf_bytes>0 THEN
  IF a.imports>=a.max_imports THEN RAISE EXCEPTION 'DEMO_IMPORT_LIMIT' USING ERRCODE='P7501'; END IF;
  IF pdf_bytes>a.max_bytes-a.bytes THEN RAISE EXCEPTION 'DEMO_BYTE_LIMIT' USING ERRCODE='P7502'; END IF;
  UPDATE demo_access SET imports=imports+1,bytes=bytes+pdf_bytes WHERE user_id=a.user_id;
 ELSIF work='INVESTIGATION' AND pdf_bytes=0 THEN
  IF a.investigations>=a.max_investigations THEN RAISE EXCEPTION 'DEMO_INVESTIGATION_LIMIT' USING ERRCODE='P7503'; END IF;
  UPDATE demo_access SET investigations=investigations+1 WHERE user_id=a.user_id;
 ELSE RAISE EXCEPTION 'Invalid demo admission';
 END IF;
END $$;
REVOKE ALL ON FUNCTION reserve_demo_work(text,bigint) FROM PUBLIC,investigator_runtime;

CREATE OR REPLACE FUNCTION enqueue_ingestion(job uuid, version uuid, request uuid, digest text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE size bigint;
BEGIN
 SELECT octet_length(v.original_pdf) INTO size FROM policy_versions v WHERE v.id=version AND can_write_policy(v.policy_id);
 IF NOT FOUND THEN RAISE EXCEPTION 'Denied' USING ERRCODE='42501'; END IF;
 PERFORM reserve_demo_work('IMPORT',size);
 INSERT INTO ingestion_tasks(id,version_id,requested_by,request_key,payload_digest) VALUES(job,version,current_actor(),request,digest);
END $$;
CREATE OR REPLACE FUNCTION schedule_investigation(inv uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF NOT investigation_runnable(inv) THEN RAISE EXCEPTION 'Denied' USING ERRCODE='42501'; END IF;
 PERFORM reserve_demo_work('INVESTIGATION',0);
 INSERT INTO investigation_jobs(id,requested_by) VALUES(inv,current_actor());
END $$;

-- Lock order: individual quota, collective budget, job. Every transport retry reserves again.
-- Reservations commit before network I/O; a timeout/crash is deliberately not refunded.
CREATE OR REPLACE FUNCTION reserve_investigation_call(inv uuid,lease uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE a demo_access%ROWTYPE; b demo_meta_budget%ROWTYPE; demo boolean; affected integer;
BEGIN
 SELECT * INTO a FROM demo_access WHERE user_id=current_actor() FOR UPDATE;
 demo:=FOUND;
 IF demo THEN
  SELECT * INTO b FROM demo_meta_budget WHERE singleton FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'DEMO_COLLECTIVE_META_LIMIT' USING ERRCODE='P7506'; END IF;
  IF a.expires_at<=clock_timestamp() THEN RAISE EXCEPTION 'DEMO_ACCESS_EXPIRED' USING ERRCODE='P7507'; END IF;
  IF a.meta_attempts>=a.max_meta_attempts THEN RAISE EXCEPTION 'DEMO_META_LIMIT' USING ERRCODE='P7505'; END IF;
  IF b.attempts>=b.max_attempts THEN RAISE EXCEPTION 'DEMO_COLLECTIVE_META_LIMIT' USING ERRCODE='P7506'; END IF;
 END IF;
 IF NOT investigation_runnable(inv) THEN RAISE EXCEPTION 'Denied' USING ERRCODE='42501'; END IF;
 UPDATE investigation_jobs SET calls=calls+1,lease_until=least(clock_timestamp()+interval '3 minutes',deadline_at)
 WHERE id=inv AND requested_by=current_actor() AND lease_token=lease AND state='RUNNING' AND lease_until>clock_timestamp()
 AND deadline_at>clock_timestamp() AND calls<20 AND prompt_tokens+completion_tokens<40000;
 GET DIAGNOSTICS affected=ROW_COUNT;
 IF affected=0 THEN RETURN false; END IF;
 IF demo THEN
  IF a.expires_at<=clock_timestamp() THEN RAISE EXCEPTION 'DEMO_ACCESS_EXPIRED' USING ERRCODE='P7507'; END IF;
  UPDATE demo_access SET meta_attempts=meta_attempts+1 WHERE user_id=a.user_id;
  UPDATE demo_meta_budget SET attempts=attempts+1 WHERE singleton;
 END IF;
 RETURN true;
END $$;
-- CREATE OR REPLACE retains the restricted grants of the existing entry points.
