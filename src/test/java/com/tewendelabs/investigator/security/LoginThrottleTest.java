package com.tewendelabs.investigator.security;

import org.junit.jupiter.api.Test;
import org.springframework.mock.web.*;

import static org.assertj.core.api.Assertions.*;

class LoginThrottleTest {
    @Test
    void spoofedForwardingHeadersCannotResetLoginThrottle() throws Exception {
        LoginThrottle filter = new LoginThrottle();
        for (int i = 0; i < 6; i++) {
            var request = new MockHttpServletRequest("POST", "/api/auth/login");
            request.setServletPath("/api/auth/login");
            request.setRemoteAddr("192.0.2.1");
            request.addHeader("X-Forwarded-For", "198.51.100." + i);
            var response = new MockHttpServletResponse();
            var chain = new MockFilterChain();
            filter.doFilter(request, response, chain);
            if (i < 5) assertThat(chain.getRequest()).isNotNull();
            else {
                assertThat(chain.getRequest()).isNull();
                assertThat(response.getStatus()).isEqualTo(429);
                assertThat(response.getHeader("Retry-After")).isEqualTo("60");
            }
        }
    }
}
