package com.tewendelabs.investigator.documentation;

import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.TestPropertySource;

/** Retains the prior prod-profile veto as an optional compatibility safeguard. */
@ActiveProfiles({"prod", "local"})
@TestPropertySource(properties = {"app.environment=local", "springdoc.api-docs.enabled=true", "springdoc.swagger-ui.enabled=true"})
class ProductionProfileSafetyTest extends ProductionOpenApiTest {
}
