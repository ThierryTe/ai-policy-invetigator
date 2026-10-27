-- Run against this project's database as its owner after migrations.
-- Set USER_EMAIL, USER_PASSWORD, DEPARTMENT_NAME, USER_ROLE in the invoking process environment.
\set ON_ERROR_STOP on
\getenv email USER_EMAIL
\getenv password USER_PASSWORD
\getenv department DEPARTMENT_NAME
\getenv role USER_ROLE
BEGIN;
INSERT INTO organizations(id,name) VALUES('10000000-0000-0000-0000-000000000001','Local synthetic organization') ON CONFLICT DO NOTHING;
INSERT INTO departments(id,organization_id,name)
 SELECT gen_random_uuid(),'10000000-0000-0000-0000-000000000001',:'department'
 WHERE NOT EXISTS(SELECT 1 FROM departments WHERE name=:'department');
INSERT INTO app_users(id,organization_id,email,password_hash)
 VALUES(gen_random_uuid(),'10000000-0000-0000-0000-000000000001',lower(:'email'),crypt(:'password',gen_salt('bf',10)));
INSERT INTO memberships(user_id,department_id,role)
 SELECT u.id,d.id,:'role' FROM app_users u JOIN departments d ON d.organization_id=u.organization_id
 WHERE u.email=lower(:'email') AND d.name=:'department';
COMMIT;
