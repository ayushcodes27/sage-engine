package com.sage.gateway.filter;

import com.sage.gateway.service.RateLimiterService;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.core.annotation.Order;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;

@Component
@ConditionalOnProperty(name = "sage.rate-limit.enabled", havingValue = "true", matchIfMissing = true)
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

        // Extract request identifiers.
        // In production, these would typically be derived from a verified JWT.
        // Currently sourced from headers, defaulting to "anonymous" if absent.
        String tenantId = request.getHeader("X-Tenant-ID");
        String userId = request.getHeader("X-User-ID");

        if (tenantId == null) tenantId = "default_tenant";
        if (userId == null) userId = "anonymous";

        // Delegate to the RateLimiterService,
        // which executes the Lua script in Redis.
        boolean isAllowed = rateLimiterService.isAllowed(tenantId, userId);

        if (!isAllowed) {
            // Reject the request at this stage if rate limits are exceeded.
            logger.warn("Rate limit exceeded for User: {} / Tenant: {}", userId, tenantId);

            response.setStatus(HttpStatus.TOO_MANY_REQUESTS.value()); // HTTP 429
            response.setContentType("application/json");
            response.getWriter().write("{\"error\": \"Rate limit exceeded\", \"retry_after\": \"1s\"}");

            // Do not invoke filterChain.doFilter().
            // Processing terminates here and the request is not forwarded.
            return;
        }

        // Allow the request to proceed to the next filter or controller.
        filterChain.doFilter(request, response);
    }
}