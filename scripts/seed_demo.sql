-- Operator-only demo provisioning, using the existing psql/pgcrypto mechanism.
-- No startup hook, runtime privilege grant, application migration or default credential.
-- The caller streams flags and an encoded password as COPY data, not SQL literals.
BEGIN;
CREATE TEMP TABLE demo_seed_input(enabled text, environment text, password_base64 text) ON COMMIT DROP;
-- DEMO_INPUT --
DO $$
DECLARE
 input record;
 secret text;
 demo_org constant uuid := 'd3000000-0000-4000-8000-000000000001';
 security_dept constant uuid := 'd3000000-0000-4000-8000-000000000002';
 hr_dept constant uuid := 'd3000000-0000-4000-8000-000000000003';
 demo_user constant uuid := 'd3000000-0000-4000-8000-000000000004';
 demo_email constant text := 'demo@policy-investigator.local';
BEGIN
 IF (SELECT count(*) FROM pg_temp.demo_seed_input)<>1 THEN RAISE EXCEPTION 'DEMO_SEED_INPUT_INVALID'; END IF;
 SELECT * INTO input FROM pg_temp.demo_seed_input;
 IF input.enabled IS DISTINCT FROM 'true' OR input.environment IS DISTINCT FROM 'local' THEN
  RAISE EXCEPTION 'DEMO_SEED_DISABLED';
 END IF;
 secret := convert_from(decode(input.password_base64,'base64'),'UTF8');
 IF octet_length(secret) NOT BETWEEN 16 AND 72 OR secret ~ '[[:cntrl:]]' OR secret LIKE 'replace-with-%' THEN
  RAISE EXCEPTION 'DEMO_PASSWORD_INVALID';
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('ai-policy-investigator-local-demo-seed',0));
 -- Never reset or claim an existing unrelated user, organization or department.
 IF EXISTS(SELECT 1 FROM organizations WHERE id=demo_org AND name<>'AI Policy Investigator local demo')
 OR EXISTS(SELECT 1 FROM departments WHERE id=security_dept AND (organization_id<>demo_org OR name<>'Security'))
 OR EXISTS(SELECT 1 FROM departments WHERE id=hr_dept AND (organization_id<>demo_org OR name<>'HR'))
 OR EXISTS(SELECT 1 FROM app_users WHERE (id=demo_user OR email=demo_email)
           AND (id<>demo_user OR organization_id<>demo_org OR email<>demo_email)) THEN
  RAISE EXCEPTION 'DEMO_IDENTITY_COLLISION';
 END IF;
 INSERT INTO organizations(id,name) VALUES(demo_org,'AI Policy Investigator local demo') ON CONFLICT(id) DO NOTHING;
 INSERT INTO departments(id,organization_id,name) VALUES(security_dept,demo_org,'Security'),(hr_dept,demo_org,'HR') ON CONFLICT(id) DO NOTHING;
 IF EXISTS(SELECT 1 FROM app_users WHERE id=demo_user) THEN
  UPDATE app_users SET active=true,
   password_hash=CASE WHEN crypt(secret,password_hash)=password_hash THEN password_hash ELSE crypt(secret,gen_salt('bf',10)) END
   WHERE id=demo_user;
 ELSE
  INSERT INTO app_users(id,organization_id,email,password_hash) VALUES(demo_user,demo_org,demo_email,crypt(secret,gen_salt('bf',10)));
 END IF;
 INSERT INTO memberships(user_id,department_id,role) VALUES(demo_user,security_dept,'ADMIN'),(demo_user,hr_dept,'ADMIN')
 ON CONFLICT(user_id,department_id) DO UPDATE SET role='ADMIN';
END $$;
COMMIT;
