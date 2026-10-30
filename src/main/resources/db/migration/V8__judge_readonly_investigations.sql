-- Analysis is a separate capability: no content grants or write policies change.
-- Only this narrow helper needs the operator-only demo_access table. Explicit
-- actor-based checks also apply when called by a SECURITY DEFINER queue function.
CREATE FUNCTION can_analyze_policy(policy uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT EXISTS (
  SELECT 1 FROM policies p
  WHERE p.id=policy AND can_access_policy(p.organization_id,p.department_id,p.id,false)
   AND (can_write_policy(p.id) OR EXISTS (
    SELECT 1 FROM demo_access a JOIN active_identity(current_actor()) u ON u.id=a.user_id
    WHERE a.expires_at>statement_timestamp() AND u.organization_id=p.organization_id
   ))
 )
$$;
REVOKE ALL ON FUNCTION can_analyze_policy(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION can_analyze_policy(uuid) TO investigator_runtime;

-- Remain SECURITY INVOKER: every source must be visible under content RLS.
-- Count the complete valid scope, rather than merely excluding visible invalid
-- rows: missing, hidden, NULL and duplicate UUIDs must never authorize analysis.
CREATE FUNCTION investigation_scope_analyzable(baseline uuid,replacement uuid,procedures uuid[],on_date date)
RETURNS boolean LANGUAGE sql STABLE SECURITY INVOKER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT coalesce(
  on_date IS NOT NULL AND cardinality(procedures) BETWEEN 1 AND 4
  AND investigation_readable(baseline,replacement,procedures)
  AND EXISTS (
   SELECT 1 FROM policy_versions r JOIN policy_versions b ON b.id=baseline
   JOIN policies p ON p.id=r.policy_id
   WHERE r.id=replacement AND r.previous_id=b.id AND r.policy_id=b.policy_id
    AND p.kind='POLICY' AND can_analyze_policy(p.id)
  )
  AND (SELECT count(*) FROM policy_versions v JOIN policies p ON p.id=v.policy_id
   WHERE v.id=ANY(array[baseline,replacement]||procedures)
    AND can_access_policy(p.organization_id,p.department_id,p.id,false)
    AND v.status='INDEXED' AND p.external_processing_allowed AND v.effective_date<=on_date
    AND (v.id IN (baseline,replacement) OR p.kind='PROCEDURE'))=2+cardinality(procedures),false)
$$;
REVOKE ALL ON FUNCTION investigation_scope_analyzable(uuid,uuid,uuid[],date) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION investigation_scope_analyzable(uuid,uuid,uuid[],date) TO investigator_runtime;

ALTER POLICY investigation_create ON investigations WITH CHECK (
 requested_by=current_actor()
 AND investigation_scope_analyzable(baseline_id,replacement_id,procedure_ids,analysis_date)
);

CREATE OR REPLACE FUNCTION investigation_runnable(inv uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY INVOKER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT EXISTS (
  SELECT 1 FROM investigations i WHERE i.id=inv AND i.requested_by=current_actor()
   AND investigation_scope_analyzable(i.baseline_id,i.replacement_id,i.procedure_ids,i.analysis_date)
 )
$$;
-- CREATE OR REPLACE preserves the existing restricted execution grants.
-- schedule_investigation, reserve_demo_work and reserve_investigation_call are
-- deliberately unchanged: admission and every Meta attempt still reserve quota.
