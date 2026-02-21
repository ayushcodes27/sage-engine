package com.sage.gateway.controller;

import com.sage.gateway.service.ProxyService;
import com.sage.gateway.service.TrafficLogger;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpMethod;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.net.URI;
import java.net.URISyntaxException;

@RestController
public class GatewayController {

    private final ProxyService proxyService;
    private final TrafficLogger trafficLogger;

    @Value("${backend.url:https://httpbin.org/anything}")
    private String backendUrl;

    public GatewayController(ProxyService proxyService, TrafficLogger trafficLogger) {
        this.proxyService = proxyService;
        this.trafficLogger = trafficLogger;
    }
    @GetMapping("/echo")
    public ResponseEntity<String> echo() {
        return ResponseEntity.ok("{\"status\":\"ok\",\"message\":\"SAGE echo\"}");
    }
    /**
     * The Universal Handler.
     * @RequestMapping("/**") captures every single request sent to this server.
     */
    @RequestMapping("/**")
    public ResponseEntity<String> handleRequest(HttpServletRequest request,
                                                @RequestBody(required = false) String body,
                                                @RequestHeader(value = "X-Tenant-ID", defaultValue = "unknown") String tenantId,
                                                @RequestHeader(value = "X-User-ID", defaultValue = "anonymous") String userId) throws URISyntaxException {

        long startTime = System.currentTimeMillis();
        String path = request.getRequestURI();
        int statusCode = 500;

        try {
            // Build the target URL for the downstream service.
            // Example: "/api/users" → "https://httpbin.org/anything/api/users"
            String target = backendUrl + path;

            // Forward the request to the downstream service.
            // The blocking call remains lightweight when executed on virtual threads.
            ResponseEntity<String> response = proxyService.forwardRequest(
                    target,
                    HttpMethod.valueOf(request.getMethod()),
                    request,
                    body
            );

            statusCode = response.getStatusCode().value();
            return response;

        } catch (Exception e) {
            // If the backend is down, we catch it here.
            statusCode = 500;
            e.printStackTrace(); // For dev debugging
            return ResponseEntity.internalServerError().body("Gateway Error: " + e.getMessage());

        } finally {
            // Asynchronously publish the request log.
            // Logging is required even on failure to support downstream ML analysis.
            long duration = System.currentTimeMillis() - startTime;
            trafficLogger.logTraffic(tenantId, userId, path, duration, statusCode);
        }
    }
}