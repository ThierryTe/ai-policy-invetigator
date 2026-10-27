package com.tewendelabs.investigator.security;

import java.time.Instant;
import java.util.*;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.*;

import org.springframework.security.oauth2.jwt.*;
import org.springframework.security.oauth2.jose.jws.MacAlgorithm;

class JwtValidationTest {
    final SecurityConfiguration config = new SecurityConfiguration();
    final javax.crypto.spec.SecretKeySpec key = config.jwtKey(UUID.randomUUID().toString() + UUID.randomUUID());
    final JwtEncoder encoder = config.encoder(key);
    final JwtDecoder decoder = config.decoder(key, "investigator", "policy-api");

    String token(String issuer, String audience, String subject, Instant expiry) {
        var builder = JwtClaimsSet.builder().issuer(issuer).audience(List.of(audience)).subject(subject).issuedAt(Instant.now().minusSeconds(3600));
        if (expiry != null) builder.expiresAt(expiry);
        return encoder.encode(JwtEncoderParameters.from(JwsHeader.with(MacAlgorithm.HS256).build(), builder.build())).getTokenValue();
    }

    @Test
    void acceptsOnlyExpectedIssuerAudienceSubjectAndExpiration() {
        String actor = UUID.randomUUID().toString();
        Instant future = Instant.now().plusSeconds(600);
        assertThat(decoder.decode(token("investigator", "policy-api", actor, future)).getSubject()).isEqualTo(actor);
        for (String bad : List.of(token("other", "policy-api", actor, future), token("investigator", "other", actor, future), token("investigator", "policy-api", "bad", future), token("investigator", "policy-api", actor, null), token("investigator", "policy-api", actor, Instant.now().minusSeconds(120))))
            assertThatThrownBy(() -> decoder.decode(bad)).isInstanceOf(JwtException.class);
    }

    @Test
    void rejectsWeakKeysAndSignaturesFromAnotherApplication() {
        assertThatThrownBy(() -> config.jwtKey("short")).isInstanceOf(IllegalStateException.class);
        JwtDecoder other = config.decoder(config.jwtKey(UUID.randomUUID().toString() + UUID.randomUUID()), "investigator", "policy-api");
        assertThatThrownBy(() -> other.decode(token("investigator", "policy-api", UUID.randomUUID().toString(), Instant.now().plusSeconds(600)))).isInstanceOf(JwtException.class);
    }
}
