-- Explicit local operator transaction, after V7. Never called by application startup.
-- Password-bearing input is COPY data, never SQL text or command-line arguments.
BEGIN;
CREATE TEMP TABLE judge_input(encoded text) ON COMMIT DROP;
-- JUDGE_INPUT --
DO $$
DECLARE
 data jsonb; address text; secret text; org uuid; operator_id uuid; scenario uuid;
 actor uuid:=gen_random_uuid(); dept uuid:=gen_random_uuid(); expiry timestamptz;
 scope uuid[]; shared uuid[]; approved uuid[]; budget bigint;
BEGIN
 IF (SELECT count(*) FROM pg_temp.judge_input)<>1 THEN RAISE EXCEPTION 'Invalid input'; END IF;
 SELECT convert_from(decode(encoded,'base64'),'UTF8')::jsonb INTO data FROM pg_temp.judge_input;
 address:=lower(trim(data->>'email')); secret:=data->>'password';
 org:=(data->>'organization_id')::uuid; operator_id:=(data->>'operator_user_id')::uuid;
 scenario:=(data->>'investigation_id')::uuid; expiry:=(data->>'expires_at')::timestamptz;
 budget:=(data->>'shared_meta_attempts')::bigint;
 IF data->'synthetic_data_confirmed' IS DISTINCT FROM 'true'::jsonb
 OR address IS NULL OR length(address)>254 OR address !~ '^[^@[:space:]]+@[^@[:space:]]+$'
 OR secret IS NULL OR octet_length(secret) NOT BETWEEN 16 AND 72 OR secret ~ '[[:cntrl:]]'
 OR org IS NULL OR operator_id IS NULL OR scenario IS NULL OR expiry IS NULL OR expiry<=clock_timestamp()
 OR (data->>'expires_at') !~ '([zZ]|[+-][0-9]{2}:[0-9]{2})$'
 OR nullif(trim(data->>'department'),'') IS NULL OR length(data->>'department')>200
 OR (data->>'department') ~ '[[:cntrl:]]' OR budget IS NULL OR budget<=0 THEN
  RAISE EXCEPTION 'Invalid input';
 END IF;
 -- Do not claim existing users, departments, privileges or counters, even on a repeated execution.
 LOCK TABLE app_users,departments,memberships,policy_grants IN SHARE ROW EXCLUSIVE MODE;
 IF EXISTS(SELECT 1 FROM app_users WHERE lower(email)=address)
 OR EXISTS(SELECT 1 FROM departments WHERE organization_id=org AND name=trim(data->>'department'))
 OR EXISTS(SELECT 1 FROM demo_access WHERE user_id=operator_id) THEN RAISE EXCEPTION 'Identity collision'; END IF;
 PERFORM set_config('app.user_id',operator_id::text,true);
 IF NOT EXISTS(SELECT 1 FROM active_identity(operator_id) WHERE organization_id=org) THEN RAISE EXCEPTION 'Invalid operator'; END IF;
 SELECT array[i.baseline_id,i.replacement_id]||i.procedure_ids INTO scope
 FROM investigations i JOIN investigation_jobs j ON j.id=i.id JOIN investigation_assessments a ON a.investigation_id=i.id
 WHERE i.id=scenario AND j.state='COMPLETED' AND a.payload->'complete'='true'::jsonb;
 IF scope IS NULL OR (SELECT count(*) FROM policy_versions v JOIN policies p ON p.id=v.policy_id
   WHERE v.id=ANY(scope) AND v.status='INDEXED' AND p.organization_id=org
    AND EXISTS(SELECT 1 FROM actor_memberships(operator_id) m WHERE m.department_id=p.department_id AND m.role='ADMIN'))<>cardinality(scope)
 THEN RAISE EXCEPTION 'Invalid completed scenario'; END IF;
 SELECT array_agg(DISTINCT policy_id ORDER BY policy_id) INTO shared FROM policy_versions WHERE id=ANY(scope);
 SELECT array_agg(value::uuid ORDER BY value::uuid) INTO approved FROM jsonb_array_elements_text(data->'read_policy_ids');
 IF approved IS DISTINCT FROM shared THEN RAISE EXCEPTION 'Exact synthetic policy allowlist required'; END IF;
 -- A single pool covers every demo identity in this database. Subsequent provisioning cannot reset/raise it.
 PERFORM 1 FROM demo_meta_budget WHERE singleton FOR UPDATE;
 UPDATE demo_meta_budget SET max_attempts=budget WHERE singleton AND max_attempts=0 AND attempts=0;
 IF NOT EXISTS(SELECT 1 FROM demo_meta_budget WHERE singleton AND max_attempts=budget) THEN RAISE EXCEPTION 'Shared budget mismatch'; END IF;
 INSERT INTO departments(id,organization_id,name) VALUES(dept,org,trim(data->>'department'));
 INSERT INTO app_users(id,organization_id,email,password_hash) VALUES(actor,org,address,crypt(secret,gen_salt('bf',10)));
 INSERT INTO memberships(user_id,department_id,role) VALUES(actor,dept,'ADMIN');
 INSERT INTO demo_access(user_id,department_id,expires_at,max_imports,max_bytes,max_investigations,max_pending,max_meta_attempts)
 VALUES(actor,dept,expiry,(data->>'max_imports')::integer,(data->>'max_bytes')::bigint,
  (data->>'max_investigations')::integer,(data->>'max_pending')::integer,(data->>'max_meta_attempts')::bigint);
 INSERT INTO policy_grants(policy_id,department_id,permission) SELECT unnest(shared),dept,'READ';
EXCEPTION WHEN OTHERS THEN
 -- Do not echo invalid private input or crypt/database diagnostics to the operator's terminal.
 RAISE EXCEPTION 'JUDGE_PROVISIONING_REFUSED' USING ERRCODE='P7510';
END $$;
COMMIT;
