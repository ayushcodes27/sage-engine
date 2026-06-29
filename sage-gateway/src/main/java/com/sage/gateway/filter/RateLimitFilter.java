package com.sage.gateway.filter;

import com.sage.gateway.service.RateLimiterService;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.core.annotation.Order;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Component;

import java.util.Map;
import java.util.Optional;

@Component
@Order(2)
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
        String ipAddress = rateLimiterService.extractClientIp(request);
        String routeId = config.getOrDefault("routeId", "default-route");
        boolean isAllowed = rateLimiterService.isAllowed(ipAddress, routeId);

        if (!isAllowed) {
            return Optional.of(
                    ResponseEntity.status(HttpStatus.TOO_MANY_REQUESTS)
                            .header("X-SAGE-Decision", "rate-limit")
                            .body("{\"error\": \"Too Many Requests\"}")
            );
        }

        return Optional.empty();
    }
}
