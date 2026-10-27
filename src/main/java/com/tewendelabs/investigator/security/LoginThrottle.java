package com.tewendelabs.investigator.security;

import java.io.IOException;
import java.util.*;

import jakarta.servlet.*;
import jakarta.servlet.http.*;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * Single-instance bounded limiter. Uses socket peer identity; never trusts arbitrary forwarding headers.
 */
final class LoginThrottle extends OncePerRequestFilter {
    private record Window(long start, int count) {
    }

    private final Map<String, Window> windows = new HashMap<>();

    @Override
    protected boolean shouldNotFilter(HttpServletRequest r) {
        return !r.getMethod().equals("POST") || !r.getServletPath().equals("/api/auth/login");
    }

    private synchronized boolean accept(String ip, long now) {
        windows.entrySet().removeIf(e -> now - e.getValue().start() > 60_000);
        Window w = windows.get(ip);
        if (w == null && windows.size() >= 10000) return false;
        if (w != null && w.count() >= 5) return false;
        windows.put(ip, new Window(w == null ? now : w.start(), w == null ? 1 : w.count() + 1));
        return true;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest r, HttpServletResponse s, FilterChain chain) throws ServletException, IOException {
        if (!accept(r.getRemoteAddr(), System.currentTimeMillis())) {
            s.setStatus(429);
            s.setHeader("Retry-After", "60");
            return;
        }
        chain.doFilter(r, s);
    }
}
