package com.tewendelabs.investigator.security;

import java.sql.SQLException;
import java.util.UUID;
import java.util.function.Supplier;

import jakarta.persistence.EntityManager;
import com.tewendelabs.investigator.api.ApiFailure;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * Every content operation, including worker operations, starts a fresh JPA/JDBC transaction.
 */
@Component
public class ScopedAccess {
    private final TransactionTemplate tx;
    private final JdbcTemplate jdbc;
    private final IdentityService identities;
    private final EntityManager em;
    private final DatabaseSafetyCheck safety;

    public ScopedAccess(PlatformTransactionManager manager, JdbcTemplate jdbc, IdentityService identities, EntityManager em, DatabaseSafetyCheck safety) {
        this.tx = new TransactionTemplate(manager);
        tx.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
        this.jdbc = jdbc;
        this.identities = identities;
        this.em = em;
        this.safety = safety;
    }

    public <T> T as(UUID user, Supplier<T> operation) {
        if (!safety.ready()) throw new ApiFailure(503, "STARTING_UP");
        if (user == null) throw new IllegalArgumentException("Missing actor");
        try {
            return tx.execute(status -> {
                em.clear();
                jdbc.queryForObject("select set_config('app.user_id',?,true)", String.class, user.toString());
                identities.active(user);
                try {
                    T result = operation.get();
                    em.flush();
                    return result;
                } finally {
                    em.clear();
                }
            });
        } catch (DataAccessException failure) {
            // Map only our fixed SQLSTATE vocabulary, never expose SQL or database diagnostics.
            for (Throwable cause = failure; cause != null; cause = cause.getCause()) {
                if (cause instanceof SQLException sql) {
                    String code = switch (sql.getSQLState() == null ? "" : sql.getSQLState()) {
                        case "P7501" -> "DEMO_IMPORT_LIMIT";
                        case "P7502" -> "DEMO_BYTE_LIMIT";
                        case "P7503" -> "DEMO_INVESTIGATION_LIMIT";
                        case "P7504" -> "DEMO_PENDING_LIMIT";
                        case "P7505" -> "DEMO_META_LIMIT";
                        case "P7506" -> "DEMO_COLLECTIVE_META_LIMIT";
                        case "P7507" -> "DEMO_ACCESS_EXPIRED";
                        default -> null;
                    };
                    if (code != null) throw new ApiFailure(code.equals("DEMO_ACCESS_EXPIRED") ? 401 : 429, code);
                }
            }
            throw failure;
        }
    }
}
