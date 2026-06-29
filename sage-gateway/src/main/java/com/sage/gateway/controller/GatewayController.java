package com.sage.gateway.controller;

import com.sage.gateway.filter.GatewayFilter;
import com.sage.gateway.routing.RouteDefinition;
import com.sage.gateway.routing.RouteRegistry;
import com.sage.gateway.routing.RouteResolver;
import com.sage.gateway.service.ProxyService;
import com.sage.gateway.service.TrafficLogger;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.HttpMethod;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.net.URISyntaxException;
import java.util.List;
import java.util.Collections;
import java.util.Map;
import java.util.Optional;

@RestController
public class GatewayController {

    private final ProxyService proxyService;
    private final TrafficLogger trafficLogger;
    private final RouteRegistry routeRegistry;
    private final RouteResolver routeResolver;
    private final List<GatewayFilter> availableFilters;

    public GatewayController(
            ProxyService proxyService,
            TrafficLogger trafficLogger,
            RouteResolver routeResolver,
            RouteRegistry routeRegistry,
            List<GatewayFilter> availableFilters) {
        this.proxyService = proxyService;
        this.trafficLogger = trafficLogger;
        this.routeResolver = routeResolver;
        this.routeRegistry = routeRegistry;
        this.availableFilters = availableFilters;
    }

    @GetMapping("/echo")
    public ResponseEntity<String> echo() {
        return ResponseEntity.ok("{\"status\":\"ok\",\"message\":\"SAGE echo\"}");
    }

    @RequestMapping("/**")
    public ResponseEntity<String> handleRequest(
            HttpServletRequest request,
            @RequestBody(required = false) String body,
            @RequestHeader(value = "X-Tenant-ID", defaultValue = "unknown") String tenantId,
            @RequestHeader(value = "X-User-ID", defaultValue = "anonymous") String userId)
            throws URISyntaxException {

        long startTime = System.currentTimeMillis();
        String path = request.getRequestURI();
        int statusCode = 500;
        ResponseEntity<String> finalResponse = null;
        Exception requestException = null;
        RouteDefinition matchedRoute = null;

        try {
            matchedRoute = routeResolver.resolve(path, request);

            if (matchedRoute == null) {
                statusCode = 404;
                finalResponse = ResponseEntity.status(404).body("Gateway Error: Route Not Found");
                return finalResponse;
            }

            Optional<ResponseEntity<String>> filterResult = applyPreProxyFilters(request, matchedRoute);
            if (filterResult.isPresent()) {
                finalResponse = filterResult.get();
                statusCode = finalResponse.getStatusCode().value();
                return finalResponse;
            }

            String target = buildTargetUrl(matchedRoute, request);

            finalResponse = proxyService.forwardRequest(
                    target,
                    HttpMethod.valueOf(request.getMethod()),
                    request,
                    body
            );

            statusCode = finalResponse.getStatusCode().value();
            return finalResponse;

        } catch (Exception e) {
            statusCode = 500;
            requestException = e;
            e.printStackTrace();
            finalResponse = ResponseEntity.internalServerError().body("Gateway Error: " + e.getMessage());
            return finalResponse;

        } finally {
            long duration = System.currentTimeMillis() - startTime;
            
            // Post Process filters
            for (GatewayFilter filter : availableFilters) {
                boolean shouldRun = filter.isGlobal();
                if (!shouldRun && matchedRoute != null && matchedRoute.filters() != null) {
                    shouldRun = matchedRoute.filters().containsKey(filter.getName());
                }
                
                if (shouldRun) {
                    try {
                        filter.postProcess(request, finalResponse, duration, requestException);
                    } catch (Exception ex) {
                        System.err.println("Error in postProcess for filter: " + filter.getName());
                        ex.printStackTrace();
                    }
                }
            }

            // Temporarily disabled during testing.
            trafficLogger.logTraffic(tenantId, userId, path, duration, statusCode);
        }
    }

    private Optional<ResponseEntity<String>> applyPreProxyFilters(
            HttpServletRequest request,
            RouteDefinition matchedRoute) {

        Map<String, Map<String, String>> routeFilters = matchedRoute.filters();
        if (routeFilters == null) {
            routeFilters = Collections.emptyMap();
        }

        for (GatewayFilter filter : availableFilters) {
            boolean shouldRun = filter.isGlobal();
            if (!shouldRun) {
                shouldRun = routeFilters.containsKey(filter.getName());
            }

            if (!shouldRun) {
                continue;
            }
            
            System.out.println("PIPELINE TRIGGERED: Attempting to run filter -> " + filter.getName());
            
            Map<String, String> filterConfig = routeFilters.getOrDefault(filter.getName(), Collections.emptyMap());
            Optional<ResponseEntity<String>> filterResult = filter.filter(request, filterConfig);
            if (filterResult.isPresent()) {
                return filterResult;
            }
        }

        return Optional.empty();
    }

    private String buildTargetUrl(RouteDefinition matchedRoute, HttpServletRequest request) {
        Map<String, String> proxyConfig = matchedRoute.filters() == null
                ? Collections.emptyMap()
                : matchedRoute.filters().getOrDefault("Proxy", Collections.emptyMap());

        String stripPrefix = proxyConfig.getOrDefault("stripPrefix", "");
        String requestPath = request.getRequestURI();
        String targetPath = requestPath;

        if (!stripPrefix.isBlank() && requestPath.startsWith(stripPrefix)) {
            targetPath = requestPath.substring(stripPrefix.length());
            if (targetPath.isBlank()) {
                targetPath = "/";
            }
        }

        String query = request.getQueryString();
        return matchedRoute.backendUrl() + targetPath + (query == null || query.isBlank() ? "" : "?" + query);
    }
}
