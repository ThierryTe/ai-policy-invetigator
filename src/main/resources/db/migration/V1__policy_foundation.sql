-- New investigation schema; no data or migrations imported from the reference project.
CREATE TABLE organizations (id uuid PRIMARY KEY, name text NOT NULL);
CREATE TABLE departments (id uuid PRIMARY KEY, organization_id uuid NOT NULL REFERENCES organizations, name text NOT NULL, UNIQUE(organization_id,id));
CREATE TABLE app_users (id uuid PRIMARY KEY, organization_id uuid NOT NULL REFERENCES organizations, email text NOT NULL UNIQUE, password_hash text NOT NULL, active boolean NOT NULL DEFAULT true);
CREATE TABLE memberships (user_id uuid NOT NULL REFERENCES app_users, department_id uuid NOT NULL REFERENCES departments, role text NOT NULL CHECK(role IN ('VIEWER','ANALYST','REVIEWER','ADMIN')), PRIMARY KEY(user_id,department_id));
CREATE TABLE policies (
 id uuid PRIMARY KEY, organization_id uuid NOT NULL REFERENCES organizations, department_id uuid NOT NULL,
 title varchar(200) NOT NULL, kind text NOT NULL CHECK(kind IN ('POLICY','PROCEDURE')),
 external_processing_allowed boolean NOT NULL DEFAULT false,
 FOREIGN KEY(organization_id,department_id) REFERENCES departments(organization_id,id)
);
CREATE TABLE policy_grants (policy_id uuid NOT NULL REFERENCES policies, department_id uuid NOT NULL REFERENCES departments, permission text NOT NULL CHECK(permission IN ('READ','WRITE')), PRIMARY KEY(policy_id,department_id));
CREATE TABLE policy_versions (
 id uuid PRIMARY KEY, policy_id uuid NOT NULL REFERENCES policies, sequence integer NOT NULL CHECK(sequence>0),
 previous_id uuid, effective_date date NOT NULL, filename varchar(200) NOT NULL,
 sha256 varchar(64) NOT NULL, original_pdf bytea NOT NULL CHECK(octet_length(original_pdf) BETWEEN 1 AND 10485760),
 status text NOT NULL DEFAULT 'QUEUED' CHECK(status IN ('QUEUED','INDEXED','FAILED')),
 created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(policy_id,sequence), UNIQUE(policy_id,id),
 FOREIGN KEY(policy_id,previous_id) REFERENCES policy_versions(policy_id,id)
);
CREATE TABLE document_pages (
 version_id uuid NOT NULL REFERENCES policy_versions, page_number integer NOT NULL CHECK(page_number>0),
 text text NOT NULL CHECK(length(text)<=100000), PRIMARY KEY(version_id,page_number)
);
CREATE TABLE chunks (
 id uuid PRIMARY KEY, version_id uuid NOT NULL REFERENCES policy_versions, page_number integer NOT NULL,
 start_offset integer NOT NULL CHECK(start_offset>=0), end_offset integer NOT NULL CHECK(end_offset>start_offset),
 content text NOT NULL, embedding vector(384) NOT NULL, embedding_revision varchar(160) NOT NULL,
 FOREIGN KEY(version_id,page_number) REFERENCES document_pages, UNIQUE(version_id,page_number,start_offset)
);
CREATE INDEX chunks_version_idx ON chunks(version_id);
CREATE INDEX policies_department_idx ON policies(department_id);
-- Control-plane queue contains identifiers and safe operational codes, never document text.
-- Runtime has no direct table access; narrow functions below dispatch and update leases.
CREATE TABLE ingestion_tasks (
 id uuid PRIMARY KEY, version_id uuid NOT NULL UNIQUE REFERENCES policy_versions, requested_by uuid NOT NULL REFERENCES app_users,
 request_key uuid NOT NULL, payload_digest varchar(64) NOT NULL,
 status text NOT NULL DEFAULT 'QUEUED' CHECK(status IN ('QUEUED','RUNNING','COMPLETED','FAILED')),
 stage text NOT NULL DEFAULT 'QUEUED', error_code text, attempts integer NOT NULL DEFAULT 0,
 lease_token uuid, lease_until timestamptz, created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(requested_by,request_key)
);
CREATE INDEX ingestion_dispatch_idx ON ingestion_tasks(status,lease_until,created_at);

CREATE FUNCTION current_actor() RETURNS uuid LANGUAGE sql STABLE AS $$ SELECT nullif(current_setting('app.user_id',true),'')::uuid $$;
CREATE FUNCTION can_access_policy(org uuid, dept uuid, policy uuid, writing boolean)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT EXISTS (
  SELECT 1 FROM app_users u JOIN memberships m ON m.user_id=u.id JOIN departments d ON d.id=m.department_id
  WHERE u.id=current_actor() AND u.active AND u.organization_id=org AND d.organization_id=org
   AND (NOT writing OR m.role IN ('ANALYST','ADMIN'))
   AND (m.department_id=dept OR EXISTS (
    SELECT 1 FROM policy_grants g WHERE g.policy_id=policy AND g.department_id=m.department_id
      AND (NOT writing OR g.permission='WRITE')))
 )
$$;
CREATE FUNCTION active_identity(actor uuid) RETURNS TABLE(id uuid,organization_id uuid,email text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT u.id,u.organization_id,u.email FROM app_users u WHERE u.id=actor AND u.active
$$;
CREATE FUNCTION login_identity(address text) RETURNS TABLE(id uuid,password_hash text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT u.id,u.password_hash FROM app_users u WHERE u.email=address AND u.active
$$;
CREATE FUNCTION actor_memberships(actor uuid) RETURNS TABLE(department_id uuid,department_name text,role text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT m.department_id,d.name,m.role FROM memberships m JOIN app_users u ON u.id=m.user_id JOIN departments d ON d.id=m.department_id
 WHERE u.id=actor AND u.active AND d.organization_id=u.organization_id
$$;

ALTER TABLE policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE policies FORCE ROW LEVEL SECURITY;
CREATE POLICY policy_read ON policies FOR SELECT USING(can_access_policy(organization_id,department_id,id,false));
CREATE POLICY policy_insert ON policies FOR INSERT WITH CHECK(can_access_policy(organization_id,department_id,id,true));
CREATE POLICY policy_update ON policies FOR UPDATE USING(can_access_policy(organization_id,department_id,id,true)) WITH CHECK(can_access_policy(organization_id,department_id,id,true));

CREATE FUNCTION can_read_version(version uuid) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM policy_versions WHERE id=version)
$$;
CREATE FUNCTION can_write_policy(policy uuid) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM policies p WHERE p.id=policy AND can_access_policy(p.organization_id,p.department_id,p.id,true))
$$;
ALTER TABLE policy_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE policy_versions FORCE ROW LEVEL SECURITY;
CREATE POLICY version_read ON policy_versions FOR SELECT USING(EXISTS(SELECT 1 FROM policies p WHERE p.id=policy_id));
CREATE POLICY version_insert ON policy_versions FOR INSERT WITH CHECK(can_write_policy(policy_id));
CREATE POLICY version_update ON policy_versions FOR UPDATE USING(can_write_policy(policy_id)) WITH CHECK(can_write_policy(policy_id));
ALTER TABLE document_pages ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_pages FORCE ROW LEVEL SECURITY;
CREATE POLICY page_read ON document_pages FOR SELECT USING(can_read_version(version_id));
CREATE POLICY page_insert ON document_pages FOR INSERT WITH CHECK(EXISTS(SELECT 1 FROM policy_versions v WHERE v.id=version_id AND can_write_policy(v.policy_id) AND v.status='QUEUED'));
ALTER TABLE chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE chunks FORCE ROW LEVEL SECURITY;
CREATE POLICY chunk_read ON chunks FOR SELECT USING(can_read_version(version_id));
CREATE POLICY chunk_insert ON chunks FOR INSERT WITH CHECK(EXISTS(SELECT 1 FROM policy_versions v WHERE v.id=version_id AND can_write_policy(v.policy_id) AND v.status='QUEUED'));

CREATE FUNCTION enforce_version_immutability() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (to_jsonb(NEW)-'status') IS DISTINCT FROM (to_jsonb(OLD)-'status') THEN
  RAISE EXCEPTION 'Immutable policy version' USING ERRCODE='23514';
 END IF;
 IF OLD.status <> 'QUEUED' AND NEW.status <> OLD.status THEN
  RAISE EXCEPTION 'Terminal version status' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER immutable_version BEFORE UPDATE ON policy_versions FOR EACH ROW EXECUTE FUNCTION enforce_version_immutability();
CREATE FUNCTION validate_source_span() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE source text;
BEGIN
 SELECT text INTO source FROM document_pages WHERE version_id=NEW.version_id AND page_number=NEW.page_number;
 IF source IS NULL OR NEW.end_offset > length(source) OR substring(source FROM NEW.start_offset+1 FOR NEW.end_offset-NEW.start_offset) <> NEW.content THEN
  RAISE EXCEPTION 'Invalid source span' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER source_span BEFORE INSERT ON chunks FOR EACH ROW EXECUTE FUNCTION validate_source_span();

CREATE FUNCTION enqueue_ingestion(job uuid, version uuid, request uuid, digest text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM policy_versions v WHERE v.id=version AND can_write_policy(v.policy_id)) THEN
  RAISE EXCEPTION 'Denied' USING ERRCODE='42501';
 END IF;
 INSERT INTO ingestion_tasks(id,version_id,requested_by,request_key,payload_digest) VALUES(job,version,current_actor(),request,digest);
END $$;
CREATE FUNCTION visible_job(job uuid) RETURNS TABLE(id uuid,version_id uuid,policy_id uuid,status text,stage text,error_code text,attempts integer)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT j.id,j.version_id,v.policy_id,j.status,j.stage,j.error_code,j.attempts
 FROM ingestion_tasks j JOIN policy_versions v ON v.id=j.version_id WHERE j.id=job
$$;
CREATE FUNCTION previous_submission(request uuid) RETURNS TABLE(job_id uuid,version_id uuid,policy_id uuid,payload_digest text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT j.id,j.version_id,v.policy_id,j.payload_digest::text FROM ingestion_tasks j JOIN policy_versions v ON v.id=j.version_id
 WHERE j.requested_by=current_actor() AND j.request_key=request
$$;
CREATE FUNCTION claim_ingestion() RETURNS TABLE(id uuid,version_id uuid,requested_by uuid,lease_token uuid)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 UPDATE ingestion_tasks j SET status='FAILED',stage='FAILED',error_code='RETRY_EXHAUSTED'
 WHERE j.status='RUNNING' AND j.lease_until<now() AND j.attempts>=3;
 RETURN QUERY
 WITH next_job AS (
  SELECT j.id FROM ingestion_tasks j WHERE (j.status='QUEUED' OR (j.status='RUNNING' AND j.lease_until<now())) AND j.attempts<3
  ORDER BY j.created_at FOR UPDATE SKIP LOCKED LIMIT 1
 )
 UPDATE ingestion_tasks j SET status='RUNNING',stage='EXTRACTING',attempts=j.attempts+1,lease_token=gen_random_uuid(),lease_until=now()+interval '3 minutes'
 FROM next_job n WHERE j.id=n.id RETURNING j.id,j.version_id,j.requested_by,j.lease_token;
END $$;
CREATE FUNCTION finish_ingestion(job uuid, lease uuid, code text) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE affected integer;
BEGIN
 IF code IS NOT NULL AND code NOT IN ('ACCESS_REVOKED','INVALID_PDF','UNSUPPORTED_PDF','TEXT_LIMIT','EMPTY_TEXT','EMBEDDING_FAILED','PROCESSING_FAILED') THEN
  RAISE EXCEPTION 'Invalid error code';
 END IF;
 UPDATE ingestion_tasks SET status=CASE WHEN code IS NULL THEN 'COMPLETED' ELSE 'FAILED' END,
 stage=CASE WHEN code IS NULL THEN 'COMPLETED' ELSE 'FAILED' END,error_code=code,lease_until=NULL
 WHERE id=job AND lease_token=lease AND status='RUNNING' AND lease_until>now();
 GET DIAGNOSTICS affected=ROW_COUNT;
 RETURN affected=1;
END $$;
CREATE FUNCTION heartbeat_ingestion(job uuid,lease uuid,new_stage text) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE affected integer;
BEGIN
 IF new_stage NOT IN ('EXTRACTING','EMBEDDING','PERSISTING') THEN RAISE EXCEPTION 'Invalid stage'; END IF;
 UPDATE ingestion_tasks SET lease_until=now()+interval '3 minutes',stage=new_stage
 WHERE id=job AND lease_token=lease AND status='RUNNING' AND lease_until>now();
 GET DIAGNOSTICS affected=ROW_COUNT; RETURN affected=1;
END $$;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION current_actor(),can_access_policy(uuid,uuid,uuid,boolean),active_identity(uuid),login_identity(text),actor_memberships(uuid),can_read_version(uuid),can_write_policy(uuid),enqueue_ingestion(uuid,uuid,uuid,text),visible_job(uuid),previous_submission(uuid),claim_ingestion(),finish_ingestion(uuid,uuid,text),heartbeat_ingestion(uuid,uuid,text) FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO investigator_runtime;
GRANT SELECT,INSERT,UPDATE ON policies,policy_versions TO investigator_runtime;
GRANT SELECT,INSERT ON document_pages,chunks TO investigator_runtime;
GRANT EXECUTE ON FUNCTION current_actor(),can_access_policy(uuid,uuid,uuid,boolean),active_identity(uuid),login_identity(text),actor_memberships(uuid),can_read_version(uuid),can_write_policy(uuid),enqueue_ingestion(uuid,uuid,uuid,text),visible_job(uuid),previous_submission(uuid),claim_ingestion(),finish_ingestion(uuid,uuid,text),heartbeat_ingestion(uuid,uuid,text) TO investigator_runtime;
