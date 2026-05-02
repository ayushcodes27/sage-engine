package com.sage.gateway.config;

import com.sage.gateway.routing.RouteDefinition;
import com.sage.gateway.routing.RouteRegistry;
import org.springframework.beans.factory.annotation.Configurable;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.http.client.reactive.ReactorClientHttpConnector;
import reactor.netty.http.client.HttpClient;
import io.netty.resolver.DefaultAddressResolverGroup;

import java.util.ArrayList;
import java.util.Map;
import java.util.List;

@Configuration
public class GatewayConfig {

    @org.springframework.beans.factory.annotation.Value("${UPSTREAM_URL:http://localhost:3001}")
    private String MOCK_TARGET_BASE;

    @Bean
    public WebClient.Builder webClientBuilder() {
        return WebClient.builder();
    }

    @Bean
    public WebClient webClient(WebClient.Builder builder){
        /**
         * Creates the central WebClient instance for the Gateway.
         * * @param builder Auto-configured by Spring Boot. It comes with:
         * 1. JSON codecs (Jackson) for parsing request/response bodies.
         * 2. Micrometer hooks for tracking metrics (latency, errors).
         * 3. Standard timeout defaults.
         * @return A fully built WebClient ready to make high-concurrency requests.
         * We use this single instance throughout the app to reuse internal
         * resources (Connection Pool) rather than creating new clients per request.
         */
        HttpClient httpClient = HttpClient.create()
                .resolver(DefaultAddressResolverGroup.INSTANCE);

        return builder
                .clientConnector(new ReactorClientHttpConnector(httpClient))
                .build();
    }

    @Bean
    public RouteRegistry routeRegistry() {
        List<RouteDefinition> routes = new ArrayList<>();

        routes.add(new RouteDefinition(
                "shop-home-route",
                "/",
                MOCK_TARGET_BASE,
                proxyOnlyFilters()
        ));
        routes.add(new RouteDefinition(
                "shop-static-route",
                "/static/{asset}",
                MOCK_TARGET_BASE,
                proxyOnlyFilters()
        ));
        routes.add(new RouteDefinition(
                "shop-products-route",
                "/products",
                MOCK_TARGET_BASE,
                rateLimitedFilters("shop-browse-route")
        ));
        routes.add(new RouteDefinition(
                "shop-product-detail-route",
                "/products/{id}",
                MOCK_TARGET_BASE,
                rateLimitedFilters("shop-browse-route")
        ));
        routes.add(new RouteDefinition(
                "shop-price-route",
                "/api/price/{id}",
                MOCK_TARGET_BASE,
                rateLimitedFilters("shop-api-route")
        ));
        routes.add(new RouteDefinition(
                "shop-inventory-route",
                "/api/inventory/{id}",
                MOCK_TARGET_BASE,
                rateLimitedFilters("shop-api-route")
        ));
        routes.add(new RouteDefinition(
                "shop-search-route",
                "/api/search",
                MOCK_TARGET_BASE,
                rateLimitedFilters("shop-search-route")
        ));
        routes.add(new RouteDefinition(
                "shop-cart-route",
                "/cart",
                MOCK_TARGET_BASE,
                rateLimitedFilters("shop-cart-route")
        ));
        routes.add(new RouteDefinition(
                "shop-checkout-route",
                "/checkout",
                MOCK_TARGET_BASE,
                rateLimitedFilters("shop-checkout-route")
        ));

        routes.add(new RouteDefinition(
                "public-user-route",
                "/api/public/{segment}",
                "https://jsonplaceholder.typicode.com",
                Map.of("Proxy", Map.of("stripPrefix", "/api/public"))
        ));
        routes.add(new RouteDefinition(
                "secure-data-route",
                "/api/get",
                "https://postman-echo.com",
                Map.of(
                        "Proxy", Map.of("stripPrefix", "/api"),
                        "RateLimit", Map.of("routeId", "secure-data-route")
                )
        ));

        return new RouteRegistry(routes);
    }

    private Map<String, Map<String, String>> proxyOnlyFilters() {
        return Map.of("Proxy", Map.of());
    }

    private Map<String, Map<String, String>> rateLimitedFilters(String routeId) {
        return Map.of(
                "Proxy", Map.of(),
                "RateLimit", Map.of("routeId", routeId)
        );
    }
}
