package com.tewendelabs.investigator.documentation;

import org.junit.jupiter.api.Test;
import org.springframework.test.context.ActiveProfiles;
import static org.assertj.core.api.Assertions.assertThat;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@ActiveProfiles("documentation-disabled-test")
class DefaultOpenApiTest extends DocumentationDatabaseSupport {
    @org.springframework.beans.factory.annotation.Autowired
    org.springframework.core.env.Environment environment;
    @Test
    void docsRemainOptInWithoutLocalProfile() throws Exception {
        assertThat(environment.getProperty("app.environment")).isEqualTo("production");
        assertThat(environment.getProperty("springdoc.api-docs.enabled",Boolean.class)).isFalse();
        assertThat(environment.getProperty("springdoc.swagger-ui.enabled",Boolean.class)).isFalse();
        var actor = actor();
        mvc.perform(get("/v3/api-docs")).andExpect(status().isUnauthorized());
        mvc.perform(get("/v3/api-docs").header("Authorization", "Bearer " + actor.token())).andExpect(status().isForbidden());
        mvc.perform(get("/swagger-ui/index.html").header("Authorization", "Bearer " + actor.token())).andExpect(status().isForbidden());
    }
}
