package com.tewendelabs.investigator.security;

import java.util.*;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import com.tewendelabs.investigator.api.ApiFailure;

@Service
public class IdentityService {
    private final JdbcTemplate jdbc;

    public IdentityService(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public record Identity(UUID id, UUID organizationId, String email) {
    }

    public Identity active(UUID id) {
        return jdbc.query("select * from active_identity(?)", (rs, n) -> new Identity(rs.getObject("id", UUID.class), rs.getObject("organization_id", UUID.class), rs.getString("email")), id)
                .stream().findFirst().orElseThrow(() -> new ApiFailure(401, "UNAUTHENTICATED"));
    }

    public List<Map<String, Object>> memberships(UUID id) {
        return jdbc.queryForList("select * from actor_memberships(?)", id);
    }
}
