package com.tewendelabs.investigator.security;

import java.nio.charset.StandardCharsets;
import java.util.*;
import javax.crypto.spec.SecretKeySpec;

import com.nimbusds.jose.jwk.source.ImmutableSecret;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.*;
import org.springframework.core.env.Environment;
import org.springframework.core.env.Profiles;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configurers.AbstractHttpConfigurer;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.oauth2.core.*;
import org.springframework.security.oauth2.jose.jws.MacAlgorithm;
import org.springframework.security.oauth2.jwt.*;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import org.springframework.security.oauth2.server.resource.web.authentication.BearerTokenAuthenticationFilter;
import org.springframework.security.web.SecurityFilterChain;
import com.tewendelabs.investigator.api.ApiFailure;

@Configuration
public class SecurityConfiguration {
    @Bean
    PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }

    @Bean
    SecretKeySpec jwtKey(@Value("${app.jwt.secret}") String secret) {
        byte[] bytes = secret.getBytes(StandardCharsets.UTF_8);
        if (bytes.length < 32) throw new IllegalStateException("JWT signing key must contain at least 32 bytes");
        return new SecretKeySpec(bytes, "HmacSHA256");
    }

    @Bean
    JwtEncoder encoder(SecretKeySpec key) {
        return new NimbusJwtEncoder(new ImmutableSecret<>(key));
    }

    @Bean
    JwtDecoder decoder(SecretKeySpec key, @Value("${app.jwt.issuer}") String issuer, @Value("${app.jwt.audience}") String audience) {
        NimbusJwtDecoder decoder = NimbusJwtDecoder.withSecretKey(key).macAlgorithm(MacAlgorithm.HS256).build();
        OAuth2TokenValidator<Jwt> required = jwt -> {
            boolean valid = jwt.getExpiresAt() != null && jwt.getAudience().contains(audience);
            try {
                UUID.fromString(jwt.getSubject());
            } catch (RuntimeException e) {
                valid = false;
            }
            return valid ? OAuth2TokenValidatorResult.success() : OAuth2TokenValidatorResult.failure(new OAuth2Error("invalid_token"));
        };
        decoder.setJwtValidator(new DelegatingOAuth2TokenValidator<>(JwtValidators.createDefaultWithIssuer(issuer), required));
        return decoder;
    }

    @Bean
    SecurityFilterChain chain(HttpSecurity http, IdentityService identities, Environment environment) throws Exception {
        boolean localDocumentation = "local".equals(environment.getProperty("app.environment", "production"))
                && !environment.acceptsProfiles(Profiles.of("prod"));
        return http.csrf(AbstractHttpConfigurer::disable).formLogin(AbstractHttpConfigurer::disable).httpBasic(AbstractHttpConfigurer::disable)
                .sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .authorizeHttpRequests(a -> {
                    var documentation = a.requestMatchers("/v3/api-docs", "/v3/api-docs/**", "/v3/api-docs.yaml", "/swagger-ui.html", "/swagger-ui/**", "/webjars/swagger-ui/**");
                    if (localDocumentation) documentation.permitAll();
                    else documentation.denyAll();
                    a.requestMatchers("/api/auth/login", "/actuator/health").permitAll().anyRequest().authenticated();
                })
                .oauth2ResourceServer(o -> o.jwt(j -> j.jwtAuthenticationConverter(jwt -> {
                    try {
                        identities.active(UUID.fromString(jwt.getSubject()));
                    } catch (ApiFailure | IllegalArgumentException e) {
                        throw new OAuth2AuthenticationException(new OAuth2Error("invalid_token"));
                    }
                    return new JwtAuthenticationToken(jwt, List.of(), jwt.getSubject());
                })))
                .addFilterBefore(new LoginThrottle(), BearerTokenAuthenticationFilter.class)
                .build();
    }
}
