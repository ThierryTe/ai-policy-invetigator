-- AI output stays immutable. Review decisions and notes are append-only events.
CREATE FUNCTION can_review_investigation(inv uuid) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM investigations i
  JOIN policy_versions v ON v.id=i.replacement_id JOIN policies p ON p.id=v.policy_id
  JOIN actor_memberships(current_actor()) m ON m.department_id=p.department_id
  WHERE i.id=inv AND m.role IN ('REVIEWER','ADMIN'))
$$;
REVOKE EXECUTE ON FUNCTION can_review_investigation(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION can_review_investigation(uuid) TO investigator_runtime;

CREATE TABLE finding_reviews (
 sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 id uuid NOT NULL UNIQUE, investigation_id uuid NOT NULL REFERENCES investigations,
 finding_id uuid NOT NULL, reviewer_id uuid NOT NULL REFERENCES app_users,
 action text NOT NULL CHECK(action IN ('CONFIRM','DISMISS','ADD_NOTE')),
 note text CHECK(note IS NULL OR length(note) BETWEEN 1 AND 2000),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK(action<>'ADD_NOTE' OR note IS NOT NULL)
);
CREATE INDEX finding_reviews_investigation_idx ON finding_reviews(investigation_id,sequence);
ALTER TABLE finding_reviews ENABLE ROW LEVEL SECURITY;
ALTER TABLE finding_reviews FORCE ROW LEVEL SECURITY;
CREATE POLICY review_read ON finding_reviews FOR SELECT USING(
 EXISTS(SELECT 1 FROM investigations i WHERE i.id=investigation_id));
CREATE POLICY review_insert ON finding_reviews FOR INSERT WITH CHECK(
 reviewer_id=current_actor() AND can_review_investigation(investigation_id)
 AND EXISTS(SELECT 1 FROM investigation_assessments a,
  LATERAL jsonb_array_elements(a.payload->'assessments') f
  WHERE a.investigation_id=finding_reviews.investigation_id AND f->>'id'=finding_id::text));
REVOKE ALL ON finding_reviews FROM PUBLIC;
GRANT SELECT,INSERT ON finding_reviews TO investigator_runtime;
GRANT USAGE ON SEQUENCE finding_reviews_sequence_seq TO investigator_runtime;
