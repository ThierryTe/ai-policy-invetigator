-- Disposable synthetic startup fixture only. No Flyway execution or migrated data.
-- This deliberately minimal fixture is not evidence of production schema behavior.
CREATE ROLE fixture_owner NOLOGIN NOSUPERUSER NOBYPASSRLS;
CREATE ROLE fixture_app LOGIN PASSWORD 'qualification-synthetic-only' NOSUPERUSER NOBYPASSRLS;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO fixture_app, fixture_owner;
CREATE TABLE policies (id uuid PRIMARY KEY, organization_id uuid NOT NULL, department_id uuid NOT NULL, title varchar(200) NOT NULL, kind varchar(255) NOT NULL, external_processing_allowed boolean NOT NULL);
ALTER TABLE policies OWNER TO fixture_owner;
ALTER TABLE policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE policies FORCE ROW LEVEL SECURITY;
GRANT SELECT ON policies TO fixture_app;
DO $fixture$
DECLARE tab text;
BEGIN
  FOREACH tab IN ARRAY ARRAY['policy_versions','document_pages','chunks','investigations','requirement_extractions','investigation_assessments','finding_reviews'] LOOP
    EXECUTE format('CREATE TABLE %I (id uuid PRIMARY KEY)',tab);
    EXECUTE format('ALTER TABLE %I OWNER TO fixture_owner',tab);
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',tab);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY',tab);
  END LOOP;
END
$fixture$;
CREATE TABLE demo_access (id uuid PRIMARY KEY);
CREATE TABLE demo_meta_budget (id uuid PRIMARY KEY);
ALTER TABLE demo_access OWNER TO fixture_owner;
ALTER TABLE demo_meta_budget OWNER TO fixture_owner;
CREATE FUNCTION reserve_demo_work(text,bigint) RETURNS boolean LANGUAGE sql AS 'SELECT false';
ALTER FUNCTION reserve_demo_work(text,bigint) OWNER TO fixture_owner;
REVOKE ALL ON FUNCTION reserve_demo_work(text,bigint) FROM PUBLIC;
