package com.tewendelabs.investigator.investigation;

import java.time.Instant;
import java.util.*;

import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import com.tewendelabs.investigator.api.ApiFailure;
import com.tewendelabs.investigator.security.ScopedAccess;
import tools.jackson.databind.JsonNode;

/** Read projections of immutable, verified investigation data. No provider calls. */
@Service
@RequiredArgsConstructor
public class InvestigationDashboardService {
    private final JdbcTemplate jdbc;
    private final ScopedAccess scope;

    public enum ReviewAction { CONFIRM, DISMISS, ADD_NOTE }
    public record ReviewRequest(ReviewAction action, String note) {}
    public record ReviewEvent(UUID id, UUID findingId, UUID reviewerId, ReviewAction action,
                              String note, Instant createdAt) {}
    public record ReviewState(UUID findingId, String status, List<ReviewEvent> history) {}
    public record Node(String id, String type, String label, UUID versionId, String classification, String severity) {}
    public record Edge(String source, String target, String type) {}
    public record Graph(UUID investigationId, boolean complete, List<Node> nodes, List<Edge> edges) {}

    private Map<String, Object> investigation(UUID id) {
        return jdbc.queryForList("select * from investigations where id=?", id).stream()
                .findFirst().orElseThrow(ApiFailure::missing);
    }

    private JsonNode assessment(UUID id) {
        var rows = jdbc.queryForList("select payload::text from investigation_assessments where investigation_id=?", id);
        return rows.isEmpty() ? null : JsonContract.parse((String) rows.getFirst().get("payload"));
    }

    private boolean canReview(UUID id) {
        return Boolean.TRUE.equals(jdbc.queryForObject("select can_review_investigation(?)", Boolean.class, id));
    }

    private List<ReviewState> reviews(UUID id, JsonNode payload) {
        if (payload == null) return List.of();
        var events = jdbc.query("select * from finding_reviews where investigation_id=? order by sequence",
                (r, n) -> new ReviewEvent(r.getObject("id", UUID.class), r.getObject("finding_id", UUID.class),
                        r.getObject("reviewer_id", UUID.class), ReviewAction.valueOf(r.getString("action")),
                        r.getString("note"), r.getTimestamp("created_at").toInstant()), id);
        var result = new ArrayList<ReviewState>();
        for (var finding : payload.path("assessments")) {
            UUID findingId = UUID.fromString(finding.path("id").asString());
            var history = events.stream().filter(e -> e.findingId().equals(findingId)).toList();
            String status = finding.path("reviewStatus").asString();
            for (var event : history) {
                if (event.action() == ReviewAction.CONFIRM) status = "CONFIRMED";
                if (event.action() == ReviewAction.DISMISS) status = "DISMISSED";
            }
            result.add(new ReviewState(findingId, status, history));
        }
        return List.copyOf(result);
    }

    public Map<String, Object> findings(UUID actor, UUID id) {
        return scope.as(actor, () -> {
            investigation(id);
            var rows = jdbc.queryForList("select payload::text,model,prompt_version,schema_version from investigation_assessments where investigation_id=?", id);
            var result = new LinkedHashMap<String, Object>();
            JsonNode payload = null;
            if (rows.isEmpty()) {
                result.put("complete", false);
                result.put("changes", List.of());
                result.put("assessments", List.of());
                result.put("progress", jdbc.queryForList("select * from investigation_progress(?)", id).getFirst());
            } else {
                result.putAll(rows.getFirst());
                payload = JsonContract.parse((String) result.get("payload"));
                result.put("payload", payload);
            }
            result.put("canReview", canReview(id));
            result.put("reviews", reviews(id, payload));
            return result;
        });
    }

    public ReviewState review(UUID actor, UUID id, UUID findingId, ReviewRequest request) {
        if (request == null || request.action() == null || request.note() != null && request.note().length() > 2000
                || request.action() == ReviewAction.ADD_NOTE && (request.note() == null || request.note().isBlank()))
            throw new ApiFailure(400, "INVALID_REVIEW");
        String note = request.note() == null || request.note().isBlank() ? null : request.note().strip();
        return scope.as(actor, () -> {
            investigation(id);
            var payload = assessment(id);
            if (payload == null) throw ApiFailure.missing();
            boolean exists = false;
            for (var f : payload.path("assessments")) exists |= findingId.toString().equals(f.path("id").asString());
            if (!exists) throw ApiFailure.missing();
            if (!canReview(id)) throw new ApiFailure(403, "REVIEW_PERMISSION_REQUIRED");
            // Serializes review ordering; the database identity sequence defines history order.
            jdbc.queryForObject("select pg_advisory_xact_lock(hashtextextended(?,0))", Object.class, id.toString());
            jdbc.update("insert into finding_reviews(id,investigation_id,finding_id,reviewer_id,action,note) values(?,?,?,?,?,?)",
                    UUID.randomUUID(), id, findingId, actor, request.action().name(), note);
            return reviews(id, payload).stream().filter(r -> r.findingId().equals(findingId)).findFirst().orElseThrow();
        });
    }

    public Graph graph(UUID actor, UUID id) {
        return scope.as(actor, () -> {
            var inv = investigation(id);
            var nodes = new LinkedHashMap<String, Node>();
            var edges = new LinkedHashSet<Edge>();
            UUID baseline = (UUID) inv.get("baseline_id"), replacement = (UUID) inv.get("replacement_id");
            var versions = new HashSet<UUID>(List.of(baseline, replacement));
            try { versions.addAll(List.of((UUID[]) ((java.sql.Array) inv.get("procedure_ids")).getArray())); }
            catch (java.sql.SQLException e) { throw new ApiFailure(500, "GRAPH_READ_FAILED"); }
            for (UUID version : versions.stream().sorted().toList()) {
                var v = jdbc.queryForList("select p.title,p.kind from policy_versions v join policies p on p.id=v.policy_id where v.id=?", version)
                        .stream().findFirst().orElseThrow(ApiFailure::missing);
                String type = version.equals(baseline) ? "BASELINE" : version.equals(replacement) ? "REPLACEMENT" : "PROCEDURE";
                nodes.put(version.toString(), new Node(version.toString(), type, (String) v.get("title"), version, null, null));
            }
            edges.add(new Edge(baseline.toString(), replacement.toString(), "REPLACED_BY"));
            Map<String, UUID> requirementVersions = new HashMap<>();
            var extractions = jdbc.queryForList("select version_id,payload::text from requirement_extractions where investigation_id=? order by version_id", id);
            for (var row : extractions) {
                UUID version = (UUID) row.get("version_id");
                if (!versions.contains(version)) invalid();
                for (var r : JsonContract.parse((String) row.get("payload")).path("requirements")) {
                    verifyReferences(r, Set.of(version));
                    String reqId = r.path("id").asString();
                    requirementVersions.put(reqId, version);
                    nodes.put(reqId, new Node(reqId, "REQUIREMENT", r.path("action").asString("Requirement"), version, null, null));
                    edges.add(new Edge(version.toString(), reqId, "CONTAINS"));
                }
            }
            var payload = assessment(id);
            if (payload != null) {
                for (var change : payload.path("changes")) {
                    verifyReferences(change, versions);
                    var old = change.path("baselineRequirementId");
                    var current = change.path("replacementRequirementId");
                    if (!old.isNull() && !baseline.equals(requirementVersions.get(old.asString()))) invalid();
                    if (!current.isNull() && !replacement.equals(requirementVersions.get(current.asString()))) invalid();
                    if (!old.isNull() && !current.isNull()) edges.add(new Edge(old.asString(), current.asString(), change.path("changeType").asString()));
                }
                for (var f : payload.path("assessments")) {
                    verifyReferences(f, versions);
                    String findingId = f.path("id").asString(), req = f.path("policyRequirementId").asString();
                    UUID procedure = UUID.fromString(f.path("procedureVersionId").asString());
                    if (!replacement.equals(requirementVersions.get(req)) || !versions.contains(procedure)
                            || procedure.equals(baseline) || procedure.equals(replacement)) invalid();
                    nodes.put(findingId, new Node(findingId, "FINDING", f.path("classification").asString(), procedure,
                            f.path("classification").asString(), f.path("severity").asString()));
                    edges.add(new Edge(req, findingId, "ASSESSED_AS"));
                    edges.add(new Edge(findingId, procedure.toString(), "AFFECTS"));
                    for (var related : f.path("relatedProcedureRequirementIds")) {
                        if (!procedure.equals(requirementVersions.get(related.asString()))) invalid();
                        edges.add(new Edge(findingId, related.asString(), "SUPPORTED_BY"));
                    }
                }
            }
            return new Graph(id, payload != null && payload.path("complete").asBoolean(), List.copyOf(nodes.values()), List.copyOf(edges));
        });
    }

    private void verifyReferences(JsonNode item, Set<UUID> versions) {
        if (item.path("sourceReferences").isEmpty()) invalid();
        for (var ref : item.path("sourceReferences")) {
            var rows = jdbc.queryForList("select version_id,content from chunks where id=?", UUID.fromString(ref.path("sourceId").asString()));
            if (rows.isEmpty() || !versions.contains(rows.getFirst().get("version_id")) || ref.path("quote").asString().isBlank()
                    || !((String) rows.getFirst().get("content")).contains(ref.path("quote").asString())) invalid();
        }
    }

    private void invalid() { throw new ApiFailure(409, "UNVERIFIED_GRAPH_DATA"); }
}
