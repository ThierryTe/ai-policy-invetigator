-- Explicit operator use only, after migrations. Not mounted into database startup.
-- Secret input is COPY data, never a SQL literal. Existing identities are never changed.
BEGIN;
CREATE TEMP TABLE initial_admin_input(encoded text) ON COMMIT DROP;
-- INITIAL_ADMIN_INPUT --
DO $$
DECLARE
 data jsonb;
 secret text;
 address text;
 org uuid := gen_random_uuid();
 dept uuid := gen_random_uuid();
 actor uuid := gen_random_uuid();
BEGIN
 IF (SELECT count(*) FROM pg_temp.initial_admin_input) <> 1 THEN
  RAISE EXCEPTION 'INITIAL_ADMIN_INPUT_INVALID';
 END IF;
 SELECT convert_from(decode(encoded,'base64'),'UTF8')::jsonb INTO data FROM pg_temp.initial_admin_input;
 secret := data->>'password';
 address := lower(trim(data->>'email'));
 IF secret IS NULL OR octet_length(secret) NOT BETWEEN 16 AND 72
    OR secret ~ '[[:cntrl:]]' OR secret LIKE 'replace-with-%'
    OR address IS NULL OR length(address)>254 OR address !~ '^[^@[:space:]]+@[^@[:space:]]+$'
    OR nullif(trim(data->>'organization'),'') IS NULL OR length(data->>'organization')>200
    OR nullif(trim(data->>'department'),'') IS NULL OR length(data->>'department')>200
    OR (data->>'organization') ~ '[[:cntrl:]]' OR (data->>'department') ~ '[[:cntrl:]]' THEN
  RAISE EXCEPTION 'INITIAL_ADMIN_INPUT_INVALID';
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('ai-policy-investigator-initial-admin',0));
 LOCK TABLE organizations,departments,app_users,memberships IN SHARE ROW EXCLUSIVE MODE;
 -- Initial bootstrap only: no password rotation, account takeover or membership escalation.
 IF EXISTS(SELECT 1 FROM organizations) OR EXISTS(SELECT 1 FROM app_users) THEN
  RAISE EXCEPTION 'INITIAL_ADMIN_REQUIRES_EMPTY_IDENTITY_STORE';
 END IF;
 INSERT INTO organizations(id,name) VALUES(org,data->>'organization');
 INSERT INTO departments(id,organization_id,name) VALUES(dept,org,data->>'department');
 INSERT INTO app_users(id,organization_id,email,password_hash)
  VALUES(actor,org,address,crypt(secret,gen_salt('bf',10)));
 INSERT INTO memberships(user_id,department_id,role) VALUES(actor,dept,'ADMIN');
END $$;
COMMIT;
