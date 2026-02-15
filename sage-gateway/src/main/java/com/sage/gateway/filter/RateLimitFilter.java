package com.sage.gateway.filter;

import com.sage.gateway.service.RateLimiterService;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.annotation.Order;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;

@Component
@Order(1) // Runs extremely early in the chain
public class RateLimitFilter extends OncePerRequestFilter {

    private static final Logger logger = LoggerFactory.getLogger(RateLimitFilter.class);
    private final RateLimiterService rateLimiterService;

    public RateLimitFilter(RateLimiterService rateLimiterService) {
        this.rateLimiterService = rateLimiterService;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain filterChain) throws ServletException, IOException {

        // 1. Extract Identifiers
        // In a real app, these might come from a JWT Token.
        // For now, we trust the headers (or default to "anonymous").
        String tenantId = request.getHeader("X-Tenant-ID");
        String userId = request.getHeader("X-User-ID");

        if (tenantId == null) tenantId = "default_tenant";
        if (userId == null) userId = "anonymous";

        // 2. Ask the Rate Limiter Service
        // This executes our Lua script in Redis
        boolean isAllowed = rateLimiterService.isAllowed(tenantId, userId);

        if (!isAllowed) {
            // 3. REJECT: The "Bouncer" stops the request here.
            logger.warn("Rate limit exceeded for User: {} / Tenant: {}", userId, tenantId);

            response.setStatus(HttpStatus.TOO_MANY_REQUESTS.value()); // HTTP 429
            response.setContentType("application/json");
            response.getWriter().write("{\"error\": \"Rate limit exceeded\", \"retry_after\": \"1s\"}");

            // Important: We do NOT call filterChain.doFilter().
            // The request stops here.
            return;
        }

        // 4. ALLOW: Pass the request to the next filter (or the Controller)
        filterChain.doFilter(request, response);
    }
}