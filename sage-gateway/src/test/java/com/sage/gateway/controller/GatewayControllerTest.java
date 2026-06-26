package com.sage.gateway.controller;

import com.sage.gateway.filter.GatewayFilter;
import com.sage.gateway.routing.RouteDefinition;
import com.sage.gateway.routing.RouteRegistry;
import com.sage.gateway.routing.RouteResolver;
import com.sage.gateway.service.ProxyService;
import com.sage.gateway.service.TrafficLogger;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpMethod;
import org.springframework.http.ResponseEntity;
import org.springframework.mock.web.MockHttpServletRequest;

import java.net.URISyntaxException;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class GatewayControllerTest {

    @Test
    void shouldPreserveQueryStringWhenProxying() throws URISyntaxException {
        ProxyService proxyService = mock(ProxyService.class);
        TrafficLogger trafficLogger = mock(TrafficLogger.class);
        RouteResolver routeResolver = mock(RouteResolver.class);
        RouteRegistry routeRegistry = mock(RouteRegistry.class);
        GatewayController controller = new GatewayController(
                proxyService,
                trafficLogger,
                routeResolver,
                routeRegistry,
                List.<GatewayFilter>of()
        );

        MockHttpServletRequest request = new MockHttpServletRequest("GET", "/api/search");
        request.setQueryString("q=lamp");
        RouteDefinition route = new RouteDefinition(
                "shop-search-route",
                "/api/search",
                "http://localhost:3001",
                Map.of("Proxy", Map.of())
        );

        when(routeResolver.resolve("/api/search", request)).thenReturn(route);
        when(proxyService.forwardRequest(any(), any(), eq(request), any()))
                .thenReturn(ResponseEntity.ok("[]"));

        ResponseEntity<String> response = controller.handleRequest(request, null, "tenant", "user");

        assertEquals(200, response.getStatusCode().value());
        verify(proxyService).forwardRequest(
                eq("http://localhost:3001/api/search?q=lamp"),
                eq(HttpMethod.GET),
                eq(request),
                eq(null)
        );
    }

    @Test
    void shouldApplyProxyStripPrefixWhenConfigured() throws URISyntaxException {
        ProxyService proxyService = mock(ProxyService.class);
        TrafficLogger trafficLogger = mock(TrafficLogger.class);
        RouteResolver routeResolver = mock(RouteResolver.class);
        RouteRegistry routeRegistry = mock(RouteRegistry.class);
        GatewayController controller = new GatewayController(
                proxyService,
                trafficLogger,
                routeResolver,
                routeRegistry,
                List.<GatewayFilter>of()
        );

        MockHttpServletRequest request = new MockHttpServletRequest("GET", "/api/public/posts");
        RouteDefinition route = new RouteDefinition(
                "public-user-route",
                "/api/public/{segment}",
                "https://jsonplaceholder.typicode.com",
                Map.of("Proxy", Map.of("stripPrefix", "/api/public"))
        );

        when(routeResolver.resolve("/api/public/posts", request)).thenReturn(route);
        when(proxyService.forwardRequest(any(), any(), eq(request), any()))
                .thenReturn(ResponseEntity.ok("[]"));

        controller.handleRequest(request, null, "tenant", "user");

        verify(proxyService).forwardRequest(
                eq("https://jsonplaceholder.typicode.com/posts"),
                eq(HttpMethod.GET),
                eq(request),
                eq(null)
        );
    }
}
