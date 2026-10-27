package com.tewendelabs.investigator.investigation;

import java.time.*;
import java.util.*;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import com.tewendelabs.investigator.api.ApiFailure;
import com.tewendelabs.investigator.security.ScopedAccess;
import com.tewendelabs.investigator.provider.PolicyReasoningProvider.Source;
import com.tewendelabs.investigator.policy.PolicyService;
import tools.jackson.databind.JsonNode;
import lombok.RequiredArgsConstructor;
import io.swagger.v3.oas.annotations.media.Schema;
import io.swagger.v3.oas.annotations.media.ArraySchema;

@Service
@RequiredArgsConstructor
public class InvestigationService {
    private final JdbcTemplate jdbc;
    private final ScopedAccess scope;

    public record Create(@Schema(requiredMode = Schema.RequiredMode.REQUIRED) UUID baselineVersionId,
                         @Schema(requiredMode = Schema.RequiredMode.REQUIRED) UUID replacementVersionId,
                         @ArraySchema(minItems = 1, maxItems = 4, arraySchema = @Schema(requiredMode = Schema.RequiredMode.REQUIRED, description = "One to four distinct indexed procedure version IDs.")) List<UUID> procedureVersionIds,
                         @Schema(requiredMode = Schema.RequiredMode.REQUIRED) LocalDate analysisDate) {
    }

    public record Snapshot(UUID id, UUID actor, UUID baseline, UUID replacement, List<UUID> procedures,
                           LocalDate date) {
        public List<UUID> versions() {
            var out = new ArrayList<>(List.of(baseline, replacement));
            out.addAll(procedures);
            return List.copyOf(out);
        }
    }

    public UUID create(UUID actor, UUID key, Create request) {
        if (key == null || request.baselineVersionId() == null || request.replacementVersionId() == null || request.procedureVersionIds() == null || request.analysisDate() == null
                || request.procedureVersionIds().isEmpty() || request.procedureVersionIds().size() > 4 || request.procedureVersionIds().stream().anyMatch(Objects::isNull))
            throw new ApiFailure(400, "INVALID_INVESTIGATION_SCOPE");
        var ids = new ArrayList<>(List.of(request.baselineVersionId(), request.replacementVersionId()));
        ids.addAll(request.procedureVersionIds());
        if (new HashSet<>(ids).size() != ids.size()) throw new ApiFailure(400, "DUPLICATE_SCOPE_VERSION");
        String digest = PolicyService.sha256(JsonContract.encode(request).getBytes(java.nio.charset.StandardCharsets.UTF_8));
        return scope.as(actor, () -> {
            jdbc.queryForObject("select pg_advisory_xact_lock(hashtextextended(?,0))", Object.class, actor + ":" + key);
            var prior = jdbc.queryForList("select id,payload_digest from investigations where requested_by=? and request_key=?", actor, key);
            if (!prior.isEmpty()) {
                if (!digest.equals(prior.getFirst().get("payload_digest")))
                    throw new ApiFailure(409, "IDEMPOTENCY_CONFLICT");
                return (UUID) prior.getFirst().get("id");
            }
            var baseline = version(request.baselineVersionId());
            var replacement = version(request.replacementVersionId());
            if (!baseline.get("policy_id").equals(replacement.get("policy_id")) || !Objects.equals(replacement.get("previous_id"), request.baselineVersionId())
                    || !"POLICY".equals(replacement.get("kind"))) throw new ApiFailure(409, "INVALID_POLICY_LINEAGE");
            for (UUID id : ids) {
                var row = version(id);
                if (!"INDEXED".equals(row.get("status"))) throw new ApiFailure(409, "VERSION_NOT_INDEXED");
                if (!Boolean.TRUE.equals(row.get("external_processing_allowed")))
                    throw new ApiFailure(409, "EXTERNAL_PROCESSING_DENIED");
                if (((java.sql.Date) row.get("effective_date")).toLocalDate().isAfter(request.analysisDate()))
                    throw new ApiFailure(409, "VERSION_NOT_EFFECTIVE");
                if (request.procedureVersionIds().contains(id) && !"PROCEDURE".equals(row.get("kind")))
                    throw new ApiFailure(400, "INVALID_PROCEDURE_SCOPE");
            }
            if (!Boolean.TRUE.equals(jdbc.queryForObject("select can_write_policy(?)", Boolean.class, replacement.get("policy_id"))))
                throw ApiFailure.missing();
            UUID id = UUID.randomUUID();
            jdbc.update("insert into investigations(id,requested_by,request_key,payload_digest,baseline_id,replacement_id,procedure_ids,analysis_date) values(?,?,?,?,?,?,?,?)", ps -> {
                ps.setObject(1, id);
                ps.setObject(2, actor);
                ps.setObject(3, key);
                ps.setString(4, digest);
                ps.setObject(5, request.baselineVersionId());
                ps.setObject(6, request.replacementVersionId());
                ps.setArray(7, ps.getConnection().createArrayOf("uuid", request.procedureVersionIds().toArray()));
                ps.setObject(8, request.analysisDate());
            });
            jdbc.queryForObject("select schedule_investigation(?)", Object.class, id);
            return id;
        });
    }

    private Map<String, Object> version(UUID version) {
        return jdbc.queryForList("select v.id,v.policy_id,v.previous_id,v.effective_date,v.status,p.kind,p.external_processing_allowed from policy_versions v join policies p on p.id=v.policy_id where v.id=?", version).stream().findFirst().orElseThrow(ApiFailure::missing);
    }

    public Snapshot snapshot(UUID actor, UUID id) {
        return scope.as(actor, () -> jdbc.query("select * from investigations where id=?", (r, n) -> new Snapshot(id, r.getObject("requested_by", UUID.class), r.getObject("baseline_id", UUID.class), r.getObject("replacement_id", UUID.class), List.of((UUID[]) r.getArray("procedure_ids").getArray()), r.getDate("analysis_date").toLocalDate()), id).stream().findFirst().orElseThrow(ApiFailure::missing));
    }

    public void requireRunnable(UUID actor, UUID id) {
        scope.as(actor, () -> {
            if (!Boolean.TRUE.equals(jdbc.queryForObject("select investigation_runnable(?)", Boolean.class, id)))
                throw new ApiFailure(403, "ACCESS_OR_CONSENT_REVOKED");
            return null;
        });
    }

    public List<Source> sources(UUID actor, UUID id, UUID version) {
        var snapshot = snapshot(actor, id);
        if (!snapshot.versions().contains(version)) throw ApiFailure.missing();
        return scope.as(actor, () -> jdbc.query("select id,version_id,content from chunks where version_id=? order by page_number,start_offset", (r, n) -> new Source(r.getObject("id", UUID.class), r.getObject("version_id", UUID.class), r.getString("content")), version));
    }

    public Map<String, Object> progress(UUID actor, UUID id) {
        return scope.as(actor, () -> jdbc.queryForList("select * from investigation_progress(?)", id).stream().findFirst().orElseThrow(ApiFailure::missing));
    }

    public List<Map<String, Object>> extractions(UUID actor, UUID id) {
        snapshot(actor, id);
        return scope.as(actor, () -> jdbc.queryForList("select version_id,payload::text,model,prompt_version,schema_version from requirement_extractions where investigation_id=? order by version_id", id).stream().map(row -> {
            row.put("payload", JsonContract.parse((String) row.get("payload")));
            return row;
        }).toList());
    }

    public Map<String, Object> findings(UUID actor, UUID id) {
        snapshot(actor, id);
        var rows = scope.as(actor, () -> jdbc.queryForList("select payload::text,model,prompt_version,schema_version from investigation_assessments where investigation_id=?", id));
        if (rows.isEmpty())
            return Map.of("complete", false, "changes", List.of(), "assessments", List.of(), "progress", progress(actor, id));
        var row = rows.getFirst();
        row.put("payload", JsonContract.parse((String) row.get("payload")));
        return row;
    }

    public void consent(UUID actor, UUID policy, boolean allowed) {
        scope.as(actor, () -> {
            var rows = jdbc.queryForList("select p.id from policies p join actor_memberships(current_actor()) m on m.department_id=p.department_id where p.id=? and m.role='ADMIN'", policy);
            if (rows.isEmpty()) throw ApiFailure.missing();
            jdbc.update("update policies set external_processing_allowed=? where id=?", allowed, policy);
            return null;
        });
    }
}
