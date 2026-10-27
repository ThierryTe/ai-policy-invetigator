-- Runtime SQL and JPA must obey the same consent rule as the HTTP endpoint.
-- Privileged owner/DBA maintenance is outside the unprivileged application boundary.
CREATE FUNCTION guard_external_processing_consent() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT (SELECT rolsuper FROM pg_roles WHERE rolname=current_user)
 AND pg_has_role(current_user,'investigator_runtime','USAGE') AND (
    (TG_OP='INSERT' AND NEW.external_processing_allowed) OR
    (TG_OP='UPDATE' AND NEW.external_processing_allowed IS DISTINCT FROM OLD.external_processing_allowed)
 ) AND NOT EXISTS (
   SELECT 1 FROM actor_memberships(current_actor()) m
   WHERE m.department_id=NEW.department_id AND m.role='ADMIN'
 ) THEN RAISE EXCEPTION 'Consent change denied' USING ERRCODE='42501';
 END IF;
 RETURN NEW;
END $$;
REVOKE EXECUTE ON FUNCTION guard_external_processing_consent() FROM PUBLIC;
CREATE TRIGGER external_processing_authority BEFORE INSERT OR UPDATE ON policies
FOR EACH ROW EXECUTE FUNCTION guard_external_processing_consent();
