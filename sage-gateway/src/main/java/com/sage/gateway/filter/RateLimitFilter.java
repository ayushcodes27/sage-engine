package com.sage.gateway.filter;

import com.sage.gateway.filter.GatewayFilter;
import com.sage.gateway.service.RateLimiterService;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Component;

import java.util.Map;
import java.util.Optional;

@Component
public class RateLimitFilter implements GatewayFilter {

    private final RateLimiterService rateLimiterService;

    public RateLimitFilter(RateLimiterService rateLimiterService) {
        this.rateLimiterService = rateLimiterService;
    }

    @Override
    public String getName() {
        return "RateLimit";
    }

    @Override
    public Optional<ResponseEntity<String>> filter(HttpServletRequest request, Map<String, String> config) {

        String tenantId = request.getHeader("X-Tenant-ID");
        String userId = request.getHeader("X-User-ID");

        // The IP Address Fallback
        if (tenantId == null) tenantId = "default_tenant";
        if (userId == null) userId = request.getRemoteAddr();

        // Execute Phase 1 Redis Lua Script
        boolean isAllowed = rateLimiterService.isAllowed(tenantId, userId);

        if (!isAllowed) {
            // FAIL
            return Optional.of(
                    ResponseEntity.status(HttpStatus.TOO_MANY_REQUESTS)
                            .header("Retry-After", "1")
                            .body("{\"error\": \"Rate limit exceeded\"}")
            );
        }

        // SUCCESS: Return an empty Optional so the pipeline continues
        return Optional.empty();
    }
}