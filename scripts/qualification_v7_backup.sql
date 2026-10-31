-- Read-only backup/rehearsal evidence. Run with psql -X -qAt -v ON_ERROR_STOP=1
-- -v demo_id=<approved production UUID>. Source also requires -v snapshot=<export>.
-- Output is PRIVATE metadata, never an Actions artifact or repository attachment.
\set ON_ERROR_STOP on
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
\if :{?snapshot}
SET TRANSACTION SNAPSHOT :'snapshot';
\endif
SET LOCAL timezone = 'UTC';
SET LOCAL datestyle = 'ISO, YMD';
SET LOCAL bytea_output = 'hex';
SET LOCAL extra_float_digits = 3;
SET LOCAL statement_timeout = '10min';
SET LOCAL lock_timeout = '5s';
SELECT set_config('backup.demo_id', :'demo_id', true) AS demo_id \gset
DO $$
DECLARE demo uuid := current_setting('backup.demo_id')::uuid;
BEGIN
 IF current_database() <> 'investigator'
    OR current_setting('server_version_num')::integer NOT BETWEEN 160000 AND 169999 THEN
  RAISE EXCEPTION 'V7_BACKUP_TARGET_MISMATCH';
 END IF;
 IF (SELECT count(*) FROM public.flyway_schema_history) <> 7 OR EXISTS (
  SELECT 1 FROM public.flyway_schema_history h LEFT JOIN (VALUES
   ('1','V1__policy_foundation.sql',-1407353534),
   ('2','V2__version_job_progress.sql',-954964090),
   ('3','V3__investigations.sql',-244515294),
   ('4','V4__external_processing_authority.sql',493766585),
   ('5','V5__configurable_investigation_deadline.sql',-852692105),
   ('6','V6__finding_reviews.sql',-501431300),
   ('7','V7__judge_demo_access.sql',-568498416)
  ) e(version,script,checksum) ON h.version=e.version
  WHERE e.version IS NULL OR h.script<>e.script OR h.checksum IS DISTINCT FROM e.checksum
     OR NOT h.success OR h.type<>'SQL'
 ) OR (SELECT count(DISTINCT version) FROM public.flyway_schema_history) <> 7 THEN
  RAISE EXCEPTION 'EXACT_V1_TO_V7_HISTORY_REQUIRED';
 END IF;
 IF NOT EXISTS (
  SELECT 1 FROM public.investigations i
  JOIN public.investigation_jobs j ON j.id=i.id
  JOIN public.investigation_assessments a ON a.investigation_id=i.id
  WHERE i.id=demo AND j.state='COMPLETED' AND j.stage='COMPLETED'
    AND jsonb_typeof(a.payload->'assessments')='array'
    AND jsonb_array_length(a.payload->'assessments')>0
    AND (SELECT count(*) FROM public.requirement_extractions e
         WHERE e.investigation_id=i.id) = cardinality(i.procedure_ids)+2
    AND NOT EXISTS (
     SELECT 1 FROM unnest(ARRAY[i.baseline_id,i.replacement_id]||i.procedure_ids) s(id)
     LEFT JOIN public.policy_versions v ON v.id=s.id
     LEFT JOIN public.requirement_extractions e ON e.version_id=s.id AND e.investigation_id=i.id
     WHERE v.id IS NULL OR v.status<>'INDEXED' OR e.version_id IS NULL
    )
 ) THEN
  RAISE EXCEPTION 'EXPECTED_COMPLETED_DEMO_OR_EVIDENCE_MISSING';
 END IF;
 IF EXISTS (SELECT 1 FROM public.policy_versions
            WHERE encode(sha256(original_pdf),'hex') IS DISTINCT FROM sha256) THEN
  RAISE EXCEPTION 'STORED_PDF_CHECKSUM_MISMATCH';
 END IF;
END $$;

-- Same representation and sort on both instances. Include all public table rows
-- (PDF bytes, embeddings, jobs, reviews, quotas and Flyway history). Deliberately
-- exclude password_hash from fingerprints; never output password-derived hashes.
-- Hash individual rows before aggregation to keep aggregate memory bounded by rows.
SELECT format($query$
 SELECT jsonb_build_object('table',%L,'rows',count(*),'sha256',
  encode(sha256(convert_to(coalesce(string_agg(h,'' ORDER BY h COLLATE "C"),''),'UTF8')),'hex'))
 FROM (SELECT encode(sha256(convert_to((to_jsonb(t)-'password_hash')::text,'UTF8')),'hex') h
       FROM %I.%I t) row_hashes
$query$, tablename, schemaname, tablename)
FROM pg_tables WHERE schemaname='public' ORDER BY tablename COLLATE "C"
\gexec

SELECT jsonb_build_object('roles',jsonb_agg(to_jsonb(r) ORDER BY rolname)) FROM (
 SELECT rolname,rolsuper,rolinherit,rolcreaterole,rolcreatedb,rolcanlogin,rolreplication,
        rolconnlimit,rolbypassrls,rolvaliduntil
 FROM pg_roles WHERE rolname IN ('investigator_owner','investigator_app','investigator_runtime')
) r;
SELECT jsonb_build_object('memberships',coalesce(jsonb_agg(to_jsonb(m) ORDER BY role_name,member_name),'[]')) FROM (
 SELECT r.rolname role_name,u.rolname member_name,g.rolname grantor_name,
        a.admin_option,a.inherit_option,a.set_option
 FROM pg_auth_members a JOIN pg_roles r ON r.oid=a.roleid
 JOIN pg_roles u ON u.oid=a.member JOIN pg_roles g ON g.oid=a.grantor
 WHERE r.rolname IN ('investigator_owner','investigator_app','investigator_runtime')
    OR u.rolname IN ('investigator_owner','investigator_app','investigator_runtime')
) m;
SELECT jsonb_build_object('extensions',jsonb_agg(to_jsonb(e) ORDER BY extname)) FROM (
 SELECT extname,extversion,n.nspname schema,r.rolname owner FROM pg_extension e
 JOIN pg_namespace n ON n.oid=e.extnamespace JOIN pg_roles r ON r.oid=e.extowner
) e;
SELECT jsonb_build_object('relations',jsonb_agg(to_jsonb(t) ORDER BY name)) FROM (
 SELECT c.relname name,c.relkind,c.relrowsecurity,c.relforcerowsecurity,r.rolname owner,
  (SELECT coalesce(jsonb_agg(jsonb_build_array(
     CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END,
     pg_get_userbyid(a.grantor),a.privilege_type,a.is_grantable)
     ORDER BY a.grantee=0,pg_get_userbyid(a.grantee),pg_get_userbyid(a.grantor),a.privilege_type),'[]')
   FROM aclexplode(coalesce(c.relacl,acldefault(
    CASE WHEN c.relkind='S' THEN 's'::"char" ELSE 'r'::"char" END,c.relowner))) a) acl
 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
 JOIN pg_roles r ON r.oid=c.relowner
 WHERE n.nspname='public' AND c.relkind IN ('r','p','S','v','m')
) t;
SELECT jsonb_build_object('policies',coalesce(jsonb_agg(to_jsonb(p) ORDER BY tablename,policyname),'[]'))
FROM pg_policies p WHERE schemaname='public';
SELECT jsonb_build_object('database',d.datname,'owner',pg_get_userbyid(d.datdba),
 'encoding',pg_encoding_to_char(d.encoding),'collate',d.datcollate,'ctype',d.datctype,
 'acl',d.datacl::text) FROM pg_database d WHERE d.datname=current_database();
SELECT jsonb_build_object('schema',n.nspname,'owner',pg_get_userbyid(n.nspowner),
 'acl',n.nspacl::text) FROM pg_namespace n WHERE n.nspname='public';
SELECT jsonb_build_object('routines',coalesce(jsonb_agg(to_jsonb(f) ORDER BY signature),'[]')) FROM (
 SELECT p.proname||'('||pg_get_function_identity_arguments(p.oid)||')' signature,
  pg_get_userbyid(p.proowner) owner,
  encode(sha256(convert_to(pg_get_functiondef(p.oid),'UTF8')),'hex') definition_sha256,
  (SELECT coalesce(jsonb_agg(jsonb_build_array(
     CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END,
     pg_get_userbyid(a.grantor),a.privilege_type,a.is_grantable)
     ORDER BY a.grantee=0,pg_get_userbyid(a.grantee),pg_get_userbyid(a.grantor),a.privilege_type),'[]')
   FROM aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a) acl
 FROM pg_proc p WHERE p.pronamespace='public'::regnamespace AND p.prokind IN ('f','p')
  AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid='pg_proc'::regclass
                  AND d.objid=p.oid AND d.deptype='e')
) f;
SELECT jsonb_build_object('demo',i.id,'state',j.state,
 'extractions',(SELECT count(*) FROM public.requirement_extractions e WHERE e.investigation_id=i.id),
 'findings',jsonb_array_length(a.payload->'assessments'),
 'reviews',(SELECT count(*) FROM public.finding_reviews r WHERE r.investigation_id=i.id))
FROM public.investigations i JOIN public.investigation_jobs j ON j.id=i.id
JOIN public.investigation_assessments a ON a.investigation_id=i.id
WHERE i.id=current_setting('backup.demo_id')::uuid;
SELECT jsonb_build_object('result','V7_BACKUP_DATA_CHECK_PASS','passwordHashFingerprintVerified',false);
ROLLBACK;
