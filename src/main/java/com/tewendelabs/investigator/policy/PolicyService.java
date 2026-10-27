package com.tewendelabs.investigator.policy;

import java.nio.charset.StandardCharsets;
import java.security.*;
import java.time.LocalDate;
import java.util.*;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.data.domain.PageRequest;
import com.tewendelabs.investigator.api.ApiFailure;
import com.tewendelabs.investigator.security.*;
import com.tewendelabs.investigator.ingestion.EmbeddingGateway;
import lombok.RequiredArgsConstructor;

@Service
@RequiredArgsConstructor
public class PolicyService {
    private final ScopedAccess scope;
    private final JdbcTemplate jdbc;
    private final PolicyRepository policies;
    private final IdentityService identities;
    private final EmbeddingGateway embeddings;

    public record Upload(UUID policyId, UUID versionId, UUID jobId, String status) {
    }

    public Upload upload(UUID actor, UUID requestKey, UUID policyId, UUID departmentId, String title, String kind, UUID previousId, LocalDate effective, String filename, byte[] bytes) {
        validatePdf(filename, bytes);
        if (requestKey == null || effective == null) throw new ApiFailure(400, "INVALID_REQUEST");
        if (policyId == null && (departmentId == null || title == null || title.isBlank() || title.length() > 200 || (kind == null || !Set.of("POLICY", "PROCEDURE").contains(kind))))
            throw new ApiFailure(400, "INVALID_REQUEST");
        String hash = sha256(bytes);
        String digest = sha256(String.join("\n", String.valueOf(policyId), String.valueOf(departmentId), String.valueOf(title), String.valueOf(kind), String.valueOf(previousId), effective.toString(), filename, hash).getBytes(StandardCharsets.UTF_8));
        return scope.as(actor, () -> {
            // Serialize identical submissions per actor before creating either policy or job.
            jdbc.queryForObject("select pg_advisory_xact_lock(hashtextextended(?,0))", Object.class, actor + ":" + requestKey);
            var old = jdbc.queryForList("select * from previous_submission(?)", requestKey);
            if (!old.isEmpty()) {
                var row = old.getFirst();
                if (!digest.equals(row.get("payload_digest"))) throw new ApiFailure(409, "IDEMPOTENCY_CONFLICT");
                return new Upload((UUID) row.get("policy_id"), (UUID) row.get("version_id"), (UUID) row.get("job_id"), "ACCEPTED");
            }
            UUID target = policyId;
            int sequence = 1;
            if (target == null) {
                var identity = identities.active(actor);
                Boolean allowed = jdbc.queryForObject("select can_access_policy(?,?,null,true)", Boolean.class, identity.organizationId(), departmentId);
                if (!Boolean.TRUE.equals(allowed)) throw ApiFailure.missing();
                target = UUID.randomUUID();
                jdbc.update("insert into policies(id,organization_id,department_id,title,kind) values(?,?,?,?,?)", target, identity.organizationId(), departmentId, title.strip(), kind);
                if (previousId != null) throw new ApiFailure(400, "INVALID_PREDECESSOR");
            } else {
                var existing = jdbc.queryForList("select id from policies where id=? and can_write_policy(id) for update", target);
                if (existing.isEmpty()) throw ApiFailure.missing();
                var latest = jdbc.queryForList("select id,sequence from policy_versions where policy_id=? order by sequence desc limit 1", target);
                if (latest.isEmpty() || !latest.getFirst().get("id").equals(previousId))
                    throw new ApiFailure(409, "STALE_PREDECESSOR");
                sequence = ((Number) latest.getFirst().get("sequence")).intValue() + 1;
            }
            UUID version = UUID.randomUUID(), job = UUID.randomUUID();
            jdbc.update("insert into policy_versions(id,policy_id,sequence,previous_id,effective_date,filename,sha256,original_pdf) values(?,?,?,?,?,?,?,?)", version, target, sequence, previousId, effective, filename, hash, bytes);
            jdbc.queryForObject("select enqueue_ingestion(?,?,?,?)", Object.class, job, version, requestKey, digest);
            return new Upload(target, version, job, "QUEUED");
        });
    }

    public List<Policy> list(UUID actor, int page) {
        return scope.as(actor, () -> policies.findAll(PageRequest.of(page, 25)).getContent());
    }

    public Policy get(UUID actor, UUID id) {
        return scope.as(actor, () -> policies.findById(id).orElseThrow(ApiFailure::missing));
    }

    public List<Map<String, Object>> versions(UUID actor, UUID policy) {
        return scope.as(actor, () -> {
            policies.findById(policy).orElseThrow(ApiFailure::missing);
            return jdbc.queryForList("""
                    select v.id,v.policy_id,v.sequence,v.previous_id,v.effective_date,v.filename,v.sha256,v.status,v.created_at,
                           j.job_id,j.job_status,j.stage,j.error_code
                    from policy_versions v left join lateral version_job(v.id) j on true
                    where v.policy_id=? order by v.sequence
                    """, policy);
        });
    }

    public byte[] content(UUID actor, UUID policy, UUID version) {
        return scope.as(actor, () -> jdbc.query("select original_pdf from policy_versions where id=? and policy_id=?", (r, n) -> r.getBytes(1), version, policy).stream().findFirst().orElseThrow(ApiFailure::missing));
    }

    public Map<String, Object> job(UUID actor, UUID id) {
        return scope.as(actor, () -> jdbc.queryForList("select * from visible_job(?)", id).stream().findFirst().orElseThrow(ApiFailure::missing));
    }

    public Map<String, Object> evidence(UUID actor, UUID id) {
        return scope.as(actor, () -> jdbc.queryForList("select c.id,c.version_id,v.policy_id,c.page_number,c.start_offset,c.end_offset,c.content as excerpt from chunks c join policy_versions v on v.id=c.version_id where c.id=? and v.status='INDEXED'", id).stream().findFirst().orElseThrow(ApiFailure::missing));
    }

    public List<Map<String, Object>> search(UUID actor, UUID version, String query) {
        if (query == null || query.isBlank() || query.length() > 2000) throw new ApiFailure(400, "INVALID_QUERY");
        // Verify the version before computing even a local embedding, then recheck in the retrieval transaction.
        scope.as(actor, () -> {
            requireIndexed(version);
            return null;
        });
        String vector = EmbeddingGateway.vectorLiteral(embeddings.embed(List.of(query)).getFirst());
        return scope.as(actor, () -> {
            requireIndexed(version);
            return jdbc.queryForList("""
                    select c.id,c.version_id,c.page_number,c.start_offset,c.end_offset,c.content as excerpt,
                           1-(c.embedding <=> cast(? as vector)) as similarity
                    from chunks c join policy_versions v on v.id=c.version_id join policies p on p.id=v.policy_id
                    where c.version_id=? and c.embedding_revision=? and v.status='INDEXED'
                      and can_access_policy(p.organization_id,p.department_id,p.id,false)
                    order by c.embedding <=> cast(? as vector),c.id limit 10
                    """, vector, version, embeddings.revision, vector);
        });
    }

    private void requireIndexed(UUID version) {
        var states = jdbc.queryForList("select status from policy_versions where id=?", String.class, version);
        if (states.isEmpty()) throw ApiFailure.missing();
        if (!"INDEXED".equals(states.getFirst())) throw new ApiFailure(409, "VERSION_NOT_INDEXED");
        if (Boolean.TRUE.equals(jdbc.queryForObject("select exists(select 1 from chunks where version_id=? and embedding_revision<>?)", Boolean.class, version, embeddings.revision)))
            throw new ApiFailure(409, "EMBEDDING_REVISION_MISMATCH");
    }

    public static void validatePdf(String filename, byte[] bytes) {
        if (filename == null || filename.isBlank() || filename.length() > 200 || filename.contains("/") || filename.contains("\\") || filename.contains("..") || filename.chars().anyMatch(c -> c < 32))
            throw new ApiFailure(400, "INVALID_FILENAME");
        if (bytes.length > 10485760) throw new ApiFailure(413, "UPLOAD_TOO_LARGE");
        if (bytes.length < 5 || !new String(bytes, 0, 5, StandardCharsets.US_ASCII).equals("%PDF-"))
            throw new ApiFailure(415, "PDF_REQUIRED");
    }

    public static String sha256(byte[] bytes) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }
}
