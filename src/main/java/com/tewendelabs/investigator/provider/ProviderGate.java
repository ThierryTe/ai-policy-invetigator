package com.tewendelabs.investigator.provider;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import com.tewendelabs.investigator.security.ScopedAccess;
import com.tewendelabs.investigator.investigation.InvestigationService;
import com.tewendelabs.investigator.api.ApiFailure;

@Component
public class ProviderGate {
    private final ScopedAccess scope;
    private final JdbcTemplate jdbc;
    private final InvestigationService investigations;

    public ProviderGate(ScopedAccess scope, JdbcTemplate jdbc, InvestigationService investigations) {
        this.scope = scope;
        this.jdbc = jdbc;
        this.investigations = investigations;
    }

    public void beforeAttempt(PolicyReasoningProvider.Request request) {
        var snapshot = investigations.snapshot(request.actorId(), request.investigationId());
        scope.as(request.actorId(), () -> {
            if (!Boolean.TRUE.equals(jdbc.queryForObject("select investigation_runnable(?)", Boolean.class, request.investigationId())))
                throw new ApiFailure(403, "ACCESS_OR_CONSENT_REVOKED");
            for (var source : request.sources()) {
                if (!snapshot.versions().contains(source.versionId()))
                    throw new ApiFailure(403, "SOURCE_SCOPE_INVALID");
                var texts = jdbc.queryForList("select content from chunks where id=? and version_id=?", String.class, source.sourceId(), source.versionId());
                if (texts.size() != 1 || !texts.getFirst().equals(source.excerpt()))
                    throw new ApiFailure(403, "SOURCE_SCOPE_INVALID");
            }
            if (!Boolean.TRUE.equals(jdbc.queryForObject("select reserve_investigation_call(?,?)", Boolean.class, request.investigationId(), request.leaseToken())))
                throw new ApiFailure(409, "INVESTIGATION_BUDGET_OR_LEASE_EXHAUSTED");
            return null;
        });
    }

    public void usage(PolicyReasoningProvider.Request request, int prompt, int completion, long latency) {
        // Control-plane counters only; no source text and no visibility grants.
        jdbc.queryForObject("select record_investigation_usage(?,?,?,?,?)", Boolean.class, request.investigationId(), request.leaseToken(), prompt, completion, latency);
    }
}
