package com.tewendelabs.investigator.config;

import java.util.List;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springdoc.core.customizers.OperationCustomizer;
import io.swagger.v3.oas.models.Components;
import io.swagger.v3.oas.models.OpenAPI;
import io.swagger.v3.oas.models.info.Info;
import io.swagger.v3.oas.models.security.SecurityRequirement;
import io.swagger.v3.oas.models.security.SecurityScheme;
import io.swagger.v3.oas.models.servers.Server;
import com.tewendelabs.investigator.security.AuthController;

@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(name = "app.environment", havingValue = "local")
@Profile("!prod")
public class OpenApiConfiguration {

    @Bean
    OpenAPI policyInvestigatorApi() {
        return new OpenAPI().info(new Info().title("AI Policy Investigator API").version("0.1.0")
                        .description("Existing Phase 2/3 APIs. Findings are advisory and require human review. "
                                + "Incomplete processing never means NO_CONFLICT. Documentation contains no document data or credentials."))
                .servers(List.of(new Server().url("/")))
                .components(new Components().addSecuritySchemes("bearerAuth", new SecurityScheme()
                        .type(SecurityScheme.Type.HTTP).scheme("bearer").bearerFormat("JWT")))
                .addSecurityItem(new SecurityRequirement().addList("bearerAuth"));
    }

    @Bean
    OperationCustomizer publicLoginDocumentation() {
        // Documentation metadata only: no controller/service invocation, database access or provider call.
        return (operation, handler) -> {
            if (handler.getBeanType().equals(AuthController.class) && handler.getMethod().getName().equals("login"))
                operation.setSecurity(List.of());
            return operation;
        };
    }
}
