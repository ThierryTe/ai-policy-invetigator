package com.tewendelabs.investigator.security;

import java.time.*;
import java.util.*;
import java.nio.charset.StandardCharsets;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.oauth2.jwt.*;
import org.springframework.security.oauth2.jose.jws.MacAlgorithm;
import org.springframework.web.bind.annotation.*;
import com.tewendelabs.investigator.api.ApiFailure;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.media.ArraySchema;
import io.swagger.v3.oas.annotations.media.Content;
import io.swagger.v3.oas.annotations.media.Schema;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.responses.ApiResponses;
import io.swagger.v3.oas.annotations.headers.Header;
import io.swagger.v3.oas.annotations.tags.Tag;
import com.tewendelabs.investigator.api.documentation.ApiDocumentation;

@Tag(name = "Authentication")
@ApiResponses({
        @ApiResponse(responseCode = "400", description = "Malformed request.", content = @Content(mediaType = "application/problem+json", schema = @Schema(implementation = ApiDocumentation.SafeProblem.class))),
        @ApiResponse(responseCode = "401", description = "Invalid credentials or inactive identity. Authentication failures may have an empty body.", content = @Content(mediaType = "application/problem+json", schema = @Schema(implementation = ApiDocumentation.SafeProblem.class))),
        @ApiResponse(responseCode = "500", description = "Safe internal error.", content = @Content(mediaType = "application/problem+json", schema = @Schema(implementation = ApiDocumentation.SafeProblem.class)))
})
@RestController
@RequestMapping("/api/auth")
public class AuthController {
    private final JdbcTemplate jdbc;
    private final PasswordEncoder passwords;
    private final JwtEncoder encoder;
    private final IdentityService identities;
    private final String issuer, audience, dummyHash;

    public AuthController(JdbcTemplate jdbc, PasswordEncoder passwords, JwtEncoder encoder, IdentityService identities,
                          @Value("${app.jwt.issuer}") String issuer, @Value("${app.jwt.audience}") String audience) {
        this.jdbc = jdbc;
        this.passwords = passwords;
        this.encoder = encoder;
        this.identities = identities;
        this.issuer = issuer;
        this.audience = audience;
        dummyHash = passwords.encode(UUID.randomUUID().toString());
    }

    public record Login(@Schema(maxLength = 254, requiredMode = Schema.RequiredMode.REQUIRED) String email,
                        @Schema(format = "password", accessMode = Schema.AccessMode.WRITE_ONLY, requiredMode = Schema.RequiredMode.REQUIRED, description = "Password input only; no example value is supplied.") String password) {
    }

    @Operation(summary = "Authenticate", description = "Returns a short-lived JWT for an active account. No credentials are included in examples.")
    @ApiResponse(responseCode = "200", description = "Successful response.", content = @Content(mediaType = "application/json", schema = @Schema(implementation = ApiDocumentation.LoginResponse.class)))
    @ApiResponse(responseCode = "429", description = "Login throttled. Retry after the indicated seconds; response body is empty.", headers = @Header(name = "Retry-After", schema = @Schema(type = "integer")), content = @Content)
    @PostMapping("/login")
    public Map<String, Object> login(@RequestBody Login login) {
        if (login.email() == null || login.password() == null || login.email().length() > 254 || login.password().getBytes(StandardCharsets.UTF_8).length > 72)
            throw new ApiFailure(401, "INVALID_CREDENTIALS");
        var rows = jdbc.queryForList("select * from login_identity(?)", login.email().strip().toLowerCase(Locale.ROOT));
        boolean matches = passwords.matches(login.password(), rows.isEmpty() ? dummyHash : (String) rows.getFirst().get("password_hash"));
        if (!matches || rows.isEmpty()) throw new ApiFailure(401, "INVALID_CREDENTIALS");
        Instant now = Instant.now();
        JwtClaimsSet claims = JwtClaimsSet.builder().issuer(issuer).audience(List.of(audience)).subject(rows.getFirst().get("id").toString())
                .issuedAt(now).expiresAt(now.plusSeconds(900)).build();
        String token = encoder.encode(JwtEncoderParameters.from(JwsHeader.with(MacAlgorithm.HS256).build(), claims)).getTokenValue();
        return Map.of("token", token, "expiresIn", 900, "tokenType", "Bearer");
    }

    @Operation(summary = "Read current identity and memberships", description = "Uses current memberships, not role claims from the JWT.")
    @ApiResponse(responseCode = "200", description = "Successful response.", content = @Content(mediaType = "application/json", schema = @Schema(implementation = ApiDocumentation.CurrentIdentity.class)))
    @GetMapping("/me")
    public Map<String, Object> me(@Parameter(hidden = true) @AuthenticationPrincipal Jwt jwt) {
        UUID id = UUID.fromString(jwt.getSubject());
        return Map.of("user", identities.active(id), "memberships", identities.memberships(id));
    }
}
