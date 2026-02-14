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

    // We default to "httpbin.org" for testing.
    // In production, this would be your internal microservice URL.
    @Value("${backend.url:https://httpbin.org/anything}")
    private String backendUrl;

    public GatewayController(ProxyService proxyService, TrafficLogger trafficLogger) {
        this.proxyService = proxyService;
        this.trafficLogger = trafficLogger;
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
            // 1. Construct the Target URL
            // If user requests "/api/users", we forward to "https://httpbin.org/anything/api/users"
            String target = backendUrl + path;

            // 2. Forward the Request (The "Blocking" Call)
            // Thanks to Virtual Threads, this "block" is cheap!
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
            // 3. The "Fire-and-Forget" Log
            // Even if the request failed, we MUST log it for ML training.
            // This runs in the background (Async).
            long duration = System.currentTimeMillis() - startTime;
            trafficLogger.logTraffic(tenantId, userId, path, duration, statusCode);
        }
    }
}