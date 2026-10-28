package com.tewendelabs.investigator.documentation;

import java.util.Set;

import org.junit.jupiter.api.Test;
import org.springframework.test.context.TestPropertySource;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@TestPropertySource(properties = {"app.environment=local", "springdoc.api-docs.enabled=true", "springdoc.swagger-ui.enabled=true"})
class LocalOpenApiTest extends DocumentationDatabaseSupport {
    @org.springframework.beans.factory.annotation.Autowired
    org.springdoc.core.properties.SwaggerUiConfigProperties swaggerConfiguration;
    @Test
    void generatedContractDescribesExistingRoutesSchemasAndBearerWithoutProviderCalls() throws Exception {
        var actor = actor();
        clearInvocations(metaTransport, embeddings);
        var response = mvc.perform(get("/v3/api-docs")).andExpect(status().isOk()).andReturn().getResponse();
        String raw = response.getContentAsString();
        JsonNode spec = JsonMapper.builder().build().readTree(raw);
        assertThat(spec.path("openapi").asString()).startsWith("3.");
        assertThat(spec.path("components").path("securitySchemes").path("bearerAuth").path("scheme").asString()).isEqualTo("bearer");
        assertThat(spec.path("components").path("securitySchemes").path("bearerAuth").path("bearerFormat").asString()).isEqualTo("JWT");
        assertThat(spec.path("security").get(0).has("bearerAuth")).isTrue();
        assertThat(spec.path("paths").path("/api/auth/login").path("post").path("security").isEmpty()).isTrue();
        assertThat(spec.path("paths").path("/api/auth/login").path("post").has("security")).isTrue();
        Set<String> paths = Set.of("/api/auth/login", "/api/auth/me", "/api/policies", "/api/policies/{id}", "/api/policies/{id}/versions", "/api/policies/{id}/versions/{version}/content", "/api/jobs/{id}", "/api/evidence/{id}", "/api/versions/{id}/search", "/api/investigations", "/api/investigations/{id}", "/api/investigations/{id}/requirements", "/api/investigations/{id}/findings", "/api/policies/{id}/external-processing", "/api/investigations/{id}/graph", "/api/investigations/{id}/findings/{findingId}/reviews");
        assertThat(spec.path("paths").propertyNames()).containsExactlyInAnyOrderElementsOf(paths);
        var schemas = spec.path("components").path("schemas");
        assertThat(schemas.has("PolicyRequirement")).isTrue();
        assertThat(schemas.has("InvestigationFinding")).isTrue();
        assertThat(schemas.path("SourceEvidence").path("properties").has("page_number")).isTrue();
        assertThat(schemas.path("NewPolicyUpload").path("properties").path("file").path("format").asString()).isEqualTo("binary");
        assertThat(spec.path("paths").path("/api/policies").path("post").path("requestBody").path("content").has("multipart/form-data")).isTrue();
        assertThat(spec.path("paths").path("/api/investigations/{id}/findings").path("get").path("responses").path("200").path("content").path("application/json").path("schema").path("oneOf")).hasSize(2);
        for (String code : Set.of("400", "401", "404", "409", "500"))
            assertThat(spec.path("paths").path("/api/investigations").path("post").path("responses").has(code)).isTrue();
        assertThat(raw).doesNotContain(actor.token(), actor.hiddenTitle(), actor.hiddenPolicy().toString(), "documentation-fixture-only", "password_hash", "jdbc:", "MODEL_API_KEY", "JWT_SECRET");
        assertThat(schemas.path("CompletedFindings").path("properties").has("reviews")).isTrue();
        assertThat(spec.path("paths").path("/api/investigations/{id}/graph").path("get").path("responses").has("200")).isTrue();
        verifyNoInteractions(metaTransport, embeddings);
    }

    @Test
    void swaggerPageAssetsAndConfigurationLoadWithoutExternalCalls() throws Exception {
        clearInvocations(metaTransport, embeddings);
        mvc.perform(get("/swagger-ui.html")).andExpect(status().is3xxRedirection());
        mvc.perform(get("/swagger-ui/index.html")).andExpect(status().isOk()).andExpect(content().string(org.hamcrest.Matchers.containsString("Swagger UI")));
        mvc.perform(get("/swagger-ui/swagger-ui-bundle.js")).andExpect(status().isOk());
        mvc.perform(get("/swagger-ui/swagger-initializer.js")).andExpect(status().isOk());
        var configuration=mvc.perform(get("/v3/api-docs/swagger-config")).andExpect(status().isOk()).andExpect(jsonPath("$.url").value("/v3/api-docs")).andReturn().getResponse().getContentAsString();
        // Springdoc omits default-valued false properties from its JSON configuration.
        assertThat(swaggerConfiguration.getPersistAuthorization()).isFalse();
        assertThat(JsonMapper.builder().build().readTree(configuration).path("persistAuthorization").asBoolean(false)).isFalse();
        verifyNoInteractions(metaTransport, embeddings);
    }

    @Test
    void publicMetadataDoesNotGrantDocumentAccess() throws Exception {
        var actor = actor();
        mvc.perform(get("/v3/api-docs")).andExpect(status().isOk());
        mvc.perform(get("/api/policies")).andExpect(status().isUnauthorized());
        mvc.perform(get("/api/policies").header("Authorization", "Bearer " + actor.token())).andExpect(status().isOk()).andExpect(content().json("[]"));
        mvc.perform(get("/api/policies/" + actor.hiddenPolicy()).header("Authorization", "Bearer " + actor.token())).andExpect(status().isNotFound());
    }
}
