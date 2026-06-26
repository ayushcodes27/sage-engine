package com.sage.gateway.config;

import com.sage.gateway.routing.RouteDefinition;
import com.sage.gateway.routing.RouteRegistry;
import com.sage.gateway.routing.RouteResolver;
import jakarta.servlet.http.HttpServletRequest;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.mockito.Mockito.mock;

class GatewayConfigRouteRegistryTest {

    private RouteResolver routeResolver;

    @BeforeEach
    void setUp() {
        GatewayConfig gatewayConfig = new GatewayConfig();
        RouteRegistry routeRegistry = gatewayConfig.routeRegistry();
        routeResolver = new RouteResolver();
        routeResolver.updateTree(routeRegistry.getRoot());
    }

    @Test
    void shouldResolveMockShopRoutesUsedByLoadTests() {
        assertRoute("/", "shop-home-route");
        assertRoute("/static/style.css", "shop-static-route");
        assertRoute("/products", "shop-products-route");
        assertRoute("/products/7", "shop-product-detail-route");
        assertRoute("/api/price/7", "shop-price-route");
        assertRoute("/api/inventory/7", "shop-inventory-route");
        assertRoute("/api/search", "shop-search-route");
        assertRoute("/cart", "shop-cart-route");
        assertRoute("/checkout", "shop-checkout-route");
    }

    private void assertRoute(String path, String expectedRouteId) {
        HttpServletRequest request = mock(HttpServletRequest.class);
        RouteDefinition routeDefinition = routeResolver.resolve(path, request);
        assertNotNull(routeDefinition, () -> "Expected route to resolve for " + path);
        assertEquals(expectedRouteId, routeDefinition.id());
    }
}
