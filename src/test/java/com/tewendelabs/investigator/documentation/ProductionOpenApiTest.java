package com.tewendelabs.investigator.documentation;

import java.util.List;

import org.junit.jupiter.api.Test;
import org.springframework.test.context.TestPropertySource;

import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@TestPropertySource(properties = {"app.environment=production", "springdoc.api-docs.enabled=true", "springdoc.swagger-ui.enabled=true"})
class ProductionOpenApiTest extends DocumentationDatabaseSupport {
    @Test
    void productionDeniesDocsWithForcedFeatureFlagsAndNoProfileFile() throws Exception {
        var actor = actor();
        clearInvocations(metaTransport, embeddings);
        for (String route : List.of("/v3/api-docs", "/v3/api-docs.yaml", "/v3/api-docs/swagger-config", "/swagger-ui.html", "/swagger-ui/index.html", "/webjars/swagger-ui/index.html")) {
            mvc.perform(get(route)).andExpect(status().isUnauthorized());
            mvc.perform(get(route).header("Authorization", "Bearer " + actor.token())).andExpect(status().isForbidden());
        }
        verifyNoInteractions(metaTransport, embeddings);
    }
}
