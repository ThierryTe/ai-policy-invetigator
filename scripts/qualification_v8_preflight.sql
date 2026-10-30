-- Read-only operator check. Supply -v expected_database=... -v target_version=7|8.
-- Does not connect anywhere by itself. No row content or credentials are printed.
\set ON_ERROR_STOP on
BEGIN READ ONLY;
SELECT set_config('qualification.database', :'expected_database', true),
       set_config('qualification.version', :'target_version', true);
DO $$
DECLARE target integer := current_setting('qualification.version')::integer;
BEGIN
 IF current_database() <> current_setting('qualification.database') OR target NOT IN (7,8) THEN
  RAISE EXCEPTION 'QUALIFICATION_TARGET_MISMATCH';
 END IF;
 IF current_setting('server_version_num')::integer NOT BETWEEN 160000 AND 169999 THEN
  RAISE EXCEPTION 'POSTGRESQL_16_REQUIRED';
 END IF;
 IF (SELECT count(*) FROM pg_roles WHERE rolname IN ('investigator_owner','investigator_app','investigator_runtime')
       AND NOT rolsuper AND NOT rolbypassrls) <> 3
    OR pg_has_role('investigator_app','investigator_owner','MEMBER')
    OR NOT pg_has_role('investigator_app','investigator_runtime','MEMBER') THEN
  RAISE EXCEPTION 'UNSAFE_RUNTIME_OR_OWNER';
 END IF;
 IF has_schema_privilege('investigator_app','public','CREATE') THEN
  RAISE EXCEPTION 'RUNTIME_CAN_CREATE_PUBLIC_OBJECTS';
 END IF;
 IF (SELECT count(*) FROM pg_class c JOIN pg_roles r ON r.oid=c.relowner
      WHERE c.relnamespace='public'::regnamespace
       AND c.relname IN ('policies','policy_versions','document_pages','chunks','investigations',
                        'requirement_extractions','investigation_assessments','finding_reviews')
       AND c.relrowsecurity AND c.relforcerowsecurity AND r.rolname='investigator_owner') <> 8 THEN
  RAISE EXCEPTION 'FORCED_RLS_OR_OWNER_MISMATCH';
 END IF;
 IF (SELECT count(*) FROM pg_class c JOIN pg_roles r ON r.oid=c.relowner
      WHERE c.relnamespace='public'::regnamespace AND c.relname IN ('demo_access','demo_meta_budget')
       AND r.rolname='investigator_owner') <> 2 THEN
  RAISE EXCEPTION 'QUOTA_OWNER_MISMATCH';
 END IF;
 IF (SELECT count(*) FROM public.flyway_schema_history) <> target
    OR (SELECT count(DISTINCT version) FROM public.flyway_schema_history) <> target OR EXISTS (
  SELECT 1 FROM public.flyway_schema_history h LEFT JOIN (VALUES
   ('1','V1__policy_foundation.sql',-1407353534),
   ('2','V2__version_job_progress.sql',-954964090),
   ('3','V3__investigations.sql',-244515294),
   ('4','V4__external_processing_authority.sql',493766585),
   ('5','V5__configurable_investigation_deadline.sql',-852692105),
   ('6','V6__finding_reviews.sql',-501431300),
   ('7','V7__judge_demo_access.sql',-568498416),
   ('8','V8__judge_readonly_investigations.sql',-14567167)
  ) e(version,script,checksum) ON h.version=e.version
  WHERE e.version IS NULL OR h.version::integer>target OR h.script<>e.script
     OR h.checksum IS DISTINCT FROM e.checksum OR NOT h.success OR h.type<>'SQL'
 ) THEN
  RAISE EXCEPTION 'FLYWAY_HISTORY_MISMATCH';
 END IF;
 IF has_table_privilege('investigator_app','demo_access','SELECT,INSERT,UPDATE,DELETE,TRUNCATE')
    OR has_table_privilege('investigator_app','demo_meta_budget','SELECT,INSERT,UPDATE,DELETE,TRUNCATE')
    OR has_function_privilege('investigator_app','reserve_demo_work(text,bigint)','EXECUTE') THEN
  RAISE EXCEPTION 'QUOTA_CONTROL_PLANE_EXPOSED';
 END IF;
 IF EXISTS (SELECT 1 FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner
             WHERE p.pronamespace='public'::regnamespace AND p.prosecdef
              AND (r.rolsuper OR r.rolbypassrls)) THEN
  -- Ignore extension-owned functions; audit application-owned functions below.
  IF EXISTS (SELECT 1 FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner
              WHERE p.pronamespace='public'::regnamespace AND p.prosecdef
               AND NOT EXISTS(SELECT 1 FROM pg_depend d WHERE d.classid='pg_proc'::regclass
                              AND d.objid=p.oid AND d.deptype='e')
               AND (r.rolsuper OR r.rolbypassrls)) THEN
   RAISE EXCEPTION 'UNSAFE_DEFINER_OWNER';
  END IF;
 END IF;
 IF target=8 THEN
  IF (SELECT count(*) FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner
       WHERE p.pronamespace='public'::regnamespace
        AND p.oid IN ('can_analyze_policy(uuid)'::regprocedure,
                     'investigation_scope_analyzable(uuid,uuid,uuid[],date)'::regprocedure,
                     'investigation_runnable(uuid)'::regprocedure)
        AND p.prosecdef=(p.proname='can_analyze_policy')
        AND r.rolname='investigator_owner'
        AND p.proconfig @> ARRAY['search_path=pg_catalog, public, pg_temp']
        AND has_function_privilege('investigator_app',p.oid,'EXECUTE')
        AND NOT EXISTS(SELECT 1 FROM aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a
                       WHERE a.grantee=0 AND a.privilege_type='EXECUTE')) <> 3 THEN
   RAISE EXCEPTION 'V8_FUNCTION_BOUNDARY_MISMATCH';
  END IF;
 END IF;
END $$;
SELECT version,script,checksum,success FROM public.flyway_schema_history ORDER BY installed_rank;
SELECT state,count(*) FROM public.investigation_jobs GROUP BY state ORDER BY state;
SELECT 'V8_QUALIFICATION_PREFLIGHT_PASS' AS result;
ROLLBACK;
