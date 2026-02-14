package com.sage.gateway.config;

import org.springframework.beans.factory.annotation.Configurable;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.reactive.function.client.WebClient;

@Configuration
public class GatewayConfig {


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
        return builder.build();
    }
}
