package com.tewendelabs.investigator.security;

import java.util.UUID;
import java.util.function.Supplier;

import jakarta.persistence.EntityManager;
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
        if (!safety.ready()) throw new com.tewendelabs.investigator.api.ApiFailure(503, "STARTING_UP");
        if (user == null) throw new IllegalArgumentException("Missing actor");
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
    }
}
