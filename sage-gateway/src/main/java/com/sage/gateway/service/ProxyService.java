package com.sage.gateway.service;

import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import org.springframework.http.HttpStatus;

import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.HttpMethod;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.web.HttpMediaTypeException;
import org.springframework.web.reactive.function.client.WebClient;

import java.util.Enumeration;

@Service
public class ProxyService {

    private final WebClient webClient;

    public ProxyService(WebClient webClient){
        this.webClient = webClient;
    }
    /*
     * Core proxy execution flow:
     * - Builds the outbound request.
     * - Propagates headers from the incoming request.
     * - Forwards the request body (if present).
     * - Blocks for the downstream response (virtual-thread friendly).
     */

    @CircuitBreaker(name = "gatewayService", fallbackMethod = "forwardRequestFallback")
    public ResponseEntity<String> forwardRequest(String targetUrl, HttpMethod method, HttpServletRequest request, String body){
        var requestSpec = webClient.method(method).uri(targetUrl);

        Enumeration<String> headerNames = request.getHeaderNames();
        while(headerNames.hasMoreElements()){
            String header = headerNames.nextElement();

            // Exclude the 'Host' header since the request is forwarded to a different backend.
            // Forwarding the original host could cause incorrect routing or host validation issues.
            if (!header.equalsIgnoreCase("host")) {
                requestSpec.header(header, request.getHeader(header));
            }
        }

        if (body != null && !body.isEmpty()) {
            requestSpec.bodyValue(body);
        }
        // Sends the request, maps the response to ResponseEntity<String>,
        // and blocks for completion (safe on virtual threads).
        return requestSpec.retrieve()
                .toEntity(String.class)
                .block();
    }
    public ResponseEntity<String> forwardRequestFallback(String targetUrl, HttpMethod method, HttpServletRequest request, String body, Throwable throwable) {
        System.out.println("🚨 CIRCUIT BREAKER TRIPPED! Target: " + targetUrl);
        System.out.println("🔥 Reason: " + throwable.getMessage());

        // Gracefully handles downstream failures by returning a controlled response
        // instead of propagating the exception to the client.
        String fallbackJson = "{\"error\": \"SAGE Gateway: Service Temporarily Unavailable.\", \"status\": 503}";

        return ResponseEntity
                .status(HttpStatus.SERVICE_UNAVAILABLE)
                .header("Content-Type", "application/json")
                .body(fallbackJson);
    }
}
