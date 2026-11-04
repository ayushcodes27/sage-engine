package com.sage.gateway.filter;

import com.sage.gateway.service.RedisTelemetryService;
import jakarta.servlet.http.HttpServletRequest;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.annotation.Order;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Component;

import java.util.Map;
import java.util.Optional;

@Component
@Order(3)
public class FastPathFilter implements GatewayFilter {

    private static final Logger logger = LoggerFactory.getLogger(FastPathFilter.class);
    private final RedisTelemetryService redisTelemetryService;

    public FastPathFilter(RedisTelemetryService redisTelemetryService) {
        this.redisTelemetryService = redisTelemetryService;
    }

    @Override
    public String getName() {
        return "FastPath";
    }

    @Override
    public boolean isGlobal() {
        return true;
    }

    @Override
    public Optional<ResponseEntity<String>> filter(HttpServletRequest request, Map<String, String> config) {
        String ipAddress = resolveClientIp(request);
        
        // Ensure IP is available for subsequent filters
        request.setAttribute("X-Client-Ip", ipAddress);

        // Reviewer Item 4: Cookie-based session identity tracking
        jakarta.servlet.http.Cookie[] cookies = request.getCookies();
        String cookieSid = null;
        if (cookies != null) {
            for (jakarta.servlet.http.Cookie c : cookies) {
                if ("__sage_sid".equals(c.getName())) {
                    cookieSid = c.getValue();
                    break;
                }
            }
        }
        if (cookieSid == null || cookieSid.isBlank()) {
            cookieSid = java.util.UUID.randomUUID().toString().replace("-", "");
            request.setAttribute("SAGE-Set-Cookie", cookieSid);
            request.setAttribute("SAGE-Has-Cookie", false);
        } else {
            request.setAttribute("SAGE-Has-Cookie", true);
        }
        request.setAttribute("SAGE-Session-Id", cookieSid);
        
        if (redisTelemetryService.isIpBanned(ipAddress)) {
            logger.warn("🚨 FAST-PATH BLOCK: IP " + ipAddress + " is on the ban list.");
            return Optional.of(buildErrorResponse(HttpStatus.FORBIDDEN, "Traffic blocked by SAGE Engine Fast-Path"));
        }

        return Optional.empty();
    }

    private String resolveClientIp(HttpServletRequest request) {
        String forwarded = request.getHeader("X-Forwarded-For");
        if (forwarded != null && !forwarded.isBlank()) {
            String firstHop = forwarded.split(",")[0].trim();
            if (!firstHop.isEmpty()) {
                return firstHop;
            }
        }
        String realIp = request.getHeader("X-Real-IP");
        if (realIp != null && !realIp.isBlank()) {
            return realIp.trim();
        }
        return request.getRemoteAddr() != null ? request.getRemoteAddr() : "anonymous";
    }

    private ResponseEntity<String> buildErrorResponse(HttpStatus status, String message) {
        return ResponseEntity.status(status)
                .header("Content-Type", "application/json")
                .body("{\"error\": \"" + status.getReasonPhrase() + "\", \"message\": \"" + message + "\"}");
    }
}
